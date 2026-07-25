"""
Streaming analysis for the Medicaid provider-spending CSV.

The source file (Data/medicaid-provider-spending.csv) is very large (~11 GB /
hundreds of millions of rows), so this module never loads it fully. It streams a
bounded *sample* of rows with the stdlib ``csv`` module and computes real
spending totals plus data-quality findings that map onto the issue types the
rest of the app already understands.

Results are cached per (path, mtime, sample size) so the file is only scanned
once per configuration.
"""

import os
import csv
import re
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, 'Data', 'medicaid-provider-spending.csv')

# How many rows to sample by default (a small fraction of the full file).
DEFAULT_SAMPLE_ROWS = int(os.environ.get('CLAIMS_SAMPLE_ROWS', '100000'))

# A valid HCPCS/CPT code is 5 characters: 5 digits, or 1 letter + 4 digits.
_HCPCS_RE = re.compile(r'^[A-Za-z0-9][0-9]{4}$')

# Flag a claim line as a suspected overpayment above this paid-per-line amount.
PAID_PER_LINE_THRESHOLD = 50_000.0

# How many concrete example rows to retain for drill-down per category.
MAX_ISSUE_EXAMPLES = 20
MAX_PROVIDER_EXAMPLES = 8

# Peer comparison: only compare a provider against peers for a given code when
# there is enough volume, and only flag when they bill this many times the
# peer (code-wide) average paid-per-line.
PEER_MIN_LINES = 20
PEER_MIN_PEERS = 3
PEER_OUTLIER_MULTIPLE = 5.0

_CACHE = {}


def _hcpcs_category(code):
    """Map an HCPCS/CPT code to a human-readable clinical category.

    Level II HCPCS codes start with a letter; CPT (Level I) codes are numeric
    and fall into well-known ranges (E/M, surgery, radiology, etc.).
    """
    if not code:
        return 'Unknown / Blank'
    first = code[0].upper()
    if first.isalpha():
        letter_map = {
            'A': 'Transportation & Supplies (A)',
            'B': 'Enteral/Parenteral (B)',
            'C': 'Outpatient PPS (C)',
            'E': 'Durable Medical Equipment (E)',
            'G': 'Temporary Procedures (G)',
            'H': 'Behavioral Health (H)',
            'J': 'Drugs / Injections (J)',
            'K': 'DME Temporary (K)',
            'L': 'Orthotics/Prosthetics (L)',
            'M': 'Medical Services (M)',
            'P': 'Pathology & Lab (P)',
            'Q': 'Temporary Codes (Q)',
            'R': 'Diagnostic Radiology (R)',
            'S': 'Private Payer (S)',
            'T': 'State Medicaid (T)',
            'V': 'Vision / Hearing (V)',
        }
        return letter_map.get(first, f'Level II HCPCS ({first})')
    # Numeric CPT ranges.
    try:
        num = int(code[:5])
    except (TypeError, ValueError):
        return 'Other / Invalid'
    if num <= 1999:
        return 'Anesthesia (CPT)'
    if num <= 69999:
        return 'Surgery (CPT)'
    if num <= 79999:
        return 'Radiology (CPT)'
    if num <= 89999:
        return 'Pathology & Lab (CPT)'
    if num <= 99199:
        return 'Medicine (CPT)'
    return 'Evaluation & Management (CPT)'


def _row_snapshot(billing, servicing, hcpcs, month, patients, lines, paid, extra=None):
    """Compact, JSON-safe snapshot of a raw claim row for drill-down."""
    snap = {
        'billing': billing,
        'servicing': servicing,
        'hcpcs': hcpcs,
        'month': month,
        'patients': patients,
        'lines': lines,
        'paid': paid,
    }
    if extra:
        snap.update(extra)
    return snap


def _human_size(num_bytes):
    size = float(num_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0 or unit == 'TB':
            return f'{size:.1f} {unit}'
        size /= 1024.0
    return f'{size:.1f} TB'


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def analyze_csv(path=None, max_rows=None, force=False):
    """Stream a sample of the CSV and return an analysis dict.

    The full file is never read into memory; at most ``max_rows`` data rows are
    inspected. Results are memoized per (path, mtime, max_rows).
    """
    path = path or DEFAULT_CSV_PATH
    max_rows = max_rows or DEFAULT_SAMPLE_ROWS

    if not os.path.exists(path):
        return {'available': False, 'file_name': os.path.basename(path), 'path': path}

    mtime = os.path.getmtime(path)
    size_bytes = os.path.getsize(path)
    cache_key = (path, mtime, max_rows)
    if not force and cache_key in _CACHE:
        return _CACHE[cache_key]

    rows_analyzed = 0
    total_paid = 0.0
    total_patients = 0
    total_claim_lines = 0

    missing_billing = 0
    missing_servicing = 0
    missing_both = 0
    invalid_hcpcs = 0
    invalid_month = 0
    nonpositive_paid = 0
    payment_outliers = 0

    seen_keys = set()
    duplicate_rows = 0

    hcpcs_paid = defaultdict(float)
    hcpcs_lines = defaultdict(int)
    provider_paid = defaultdict(float)
    provider_claims = defaultdict(int)
    provider_flags = defaultdict(int)        # provider -> count of quality-flagged rows
    monthly_paid = defaultdict(float)
    monthly_lines = defaultdict(int)
    yearly_paid = defaultdict(float)         # year -> total paid

    # Financial exposure: dollars sitting on rows that carry a quality issue.
    exposure_duplicate = 0.0
    exposure_outlier = 0.0
    exposure_missing_npi = 0.0
    exposure_invalid_code = 0.0

    # Drill-down: concrete example rows per issue key and per provider, plus a
    # representative (worst) row per HCPCS code for the costliest-code table.
    issue_examples = defaultdict(list)
    provider_flag_examples = defaultdict(list)
    hcpcs_worst_line = {}   # code -> (paid_per_line, snapshot)

    # Category-level aggregation (compare spend across clinical categories).
    category_paid = defaultdict(float)
    category_lines = defaultdict(int)
    category_claims = defaultdict(int)
    category_providers = defaultdict(set)

    # Per-(provider, code) aggregation for peer benchmarking.
    pc_paid = defaultdict(float)
    pc_lines = defaultdict(int)

    date_min = None
    date_max = None
    month_re = re.compile(r'^\d{4}-\d{2}$')

    with open(path, 'r', newline='', encoding='utf-8', errors='replace') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if rows_analyzed >= max_rows:
                break
            rows_analyzed += 1

            billing = (row.get('BILLING_PROVIDER_NPI_NUM') or '').strip()
            servicing = (row.get('SERVICING_PROVIDER_NPI_NUM') or '').strip()
            hcpcs = (row.get('HCPCS_CODE') or '').strip()
            month = (row.get('CLAIM_FROM_MONTH') or '').strip()
            patients = _to_int(row.get('TOTAL_PATIENTS'))
            lines = _to_int(row.get('TOTAL_CLAIM_LINES'))
            paid = _to_float(row.get('TOTAL_PAID'))

            # ---- Totals ----
            if paid is not None:
                total_paid += paid
            if patients is not None:
                total_patients += patients
            if lines is not None:
                total_claim_lines += lines

            paid_val = paid if paid is not None else 0.0
            provider = billing or servicing
            row_flagged = False
            row_reasons = []   # human-readable reasons this row is problematic

            def _add_example(issue_key, reason):
                """Record a bounded example row for later drill-down."""
                if len(issue_examples[issue_key]) < MAX_ISSUE_EXAMPLES:
                    issue_examples[issue_key].append(
                        _row_snapshot(billing, servicing, hcpcs, month,
                                      patients, lines, paid, extra={'reason': reason})
                    )

            # ---- Data-quality checks ----
            if not billing and not servicing:
                missing_both += 1
                exposure_missing_npi += paid_val
                row_flagged = True
                reason = 'Both billing and servicing NPI are blank.'
                row_reasons.append(reason)
                _add_example('null_recipient_values', reason)
            else:
                if not billing:
                    missing_billing += 1
                    reason = 'Billing provider NPI is blank.'
                    row_reasons.append(reason)
                    _add_example('missing_billing_npi', reason)
                if not servicing:
                    missing_servicing += 1
                    reason = 'Servicing provider NPI is blank.'
                    row_reasons.append(reason)
                    _add_example('missing_servicing_npi', reason)

            if not hcpcs or not _HCPCS_RE.match(hcpcs):
                invalid_hcpcs += 1
                exposure_invalid_code += paid_val
                row_flagged = True
                reason = (f'HCPCS code "{hcpcs}" is not a valid 5-character code.'
                          if hcpcs else 'HCPCS code is blank.')
                row_reasons.append(reason)
                _add_example('improper_procedure_code', reason)

            if not month or not month_re.match(month):
                invalid_month += 1
                reason = (f'Claim month "{month}" is not in YYYY-MM format.'
                          if month else 'Claim month is blank.')
                row_reasons.append(reason)
                _add_example('invalid_month', reason)
            else:
                if date_min is None or month < date_min:
                    date_min = month
                if date_max is None or month > date_max:
                    date_max = month
                if paid is not None:
                    monthly_paid[month] += paid
                    yearly_paid[month[:4]] += paid
                if lines is not None:
                    monthly_lines[month] += lines

            if paid is not None and paid <= 0:
                nonpositive_paid += 1
                reason = f'Paid amount is {paid:,.2f} (zero or negative).'
                row_reasons.append(reason)
                _add_example('nonpositive_paid', reason)

            if paid is not None and lines:
                per_line = paid / lines
                if per_line > PAID_PER_LINE_THRESHOLD:
                    payment_outliers += 1
                    exposure_outlier += paid_val
                    row_flagged = True
                    reason = (f'Paid ${paid:,.0f} over {lines:,} line(s) = '
                              f'${per_line:,.0f}/line, above the '
                              f'${PAID_PER_LINE_THRESHOLD:,.0f} threshold '
                              f'({per_line / PAID_PER_LINE_THRESHOLD:.0f}x).')
                    row_reasons.append(reason)
                    _add_example('payment_amount_exceeded', reason)

            # ---- Duplicate detection ----
            dup_key = (billing, servicing, hcpcs, month)
            if dup_key in seen_keys:
                duplicate_rows += 1
                exposure_duplicate += paid_val
                row_flagged = True
                reason = ('Same billing NPI, servicing NPI, HCPCS code and month '
                          'already appeared earlier in the data.')
                row_reasons.append(reason)
                _add_example('duplicate_claims', reason)
            else:
                seen_keys.add(dup_key)

            # ---- Aggregations for top lists ----
            if hcpcs:
                if paid is not None:
                    hcpcs_paid[hcpcs] += paid
                if lines is not None:
                    hcpcs_lines[hcpcs] += lines
                # Track the worst (highest paid-per-line) example row per code.
                if paid is not None and lines:
                    per_line = paid / lines
                    prev = hcpcs_worst_line.get(hcpcs)
                    if prev is None or per_line > prev[0]:
                        hcpcs_worst_line[hcpcs] = (
                            per_line,
                            _row_snapshot(billing, servicing, hcpcs, month,
                                          patients, lines, paid,
                                          extra={'per_line': per_line}),
                        )
                # Category-level rollup.
                category = _hcpcs_category(hcpcs)
                if paid is not None:
                    category_paid[category] += paid
                if lines is not None:
                    category_lines[category] += lines
                category_claims[category] += 1
                if provider:
                    category_providers[category].add(provider)
                    # Per-(provider, code) rollup for peer benchmarking.
                    if paid is not None:
                        pc_paid[(provider, hcpcs)] += paid
                    if lines is not None:
                        pc_lines[(provider, hcpcs)] += lines
            if provider:
                if paid is not None:
                    provider_paid[provider] += paid
                provider_claims[provider] += 1
                if row_flagged:
                    provider_flags[provider] += 1
                    if len(provider_flag_examples[provider]) < MAX_PROVIDER_EXAMPLES:
                        provider_flag_examples[provider].append(
                            _row_snapshot(billing, servicing, hcpcs, month,
                                          patients, lines, paid,
                                          extra={'reason': '; '.join(row_reasons)})
                        )

    def _pct(count):
        return round(count / rows_analyzed * 100, 2) if rows_analyzed else 0.0

    issues = [
        {
            'key': 'null_recipient_values',
            'label': 'Missing Provider NPI (both blank)',
            'count': missing_both,
            'pct': _pct(missing_both),
            'severity': 'high',
            'description': 'Rows where both the billing and servicing provider NPI are blank, '
                           'so the claim cannot be attributed to a provider.',
            'impact': 'A claim with no provider cannot be audited, recovered, or tied to a '
                      'real entity — it may hide fraudulent or duplicate billing and breaks '
                      'any provider-level reporting.',
        },
        {
            'key': 'missing_billing_npi',
            'label': 'Missing Billing Provider NPI',
            'count': missing_billing,
            'pct': _pct(missing_billing),
            'severity': 'medium',
            'description': 'Rows missing the billing provider NPI (a servicing NPI may still be present).',
            'impact': 'Without a billing NPI you cannot confirm who was paid, complicating '
                      'payment reconciliation and recovery.',
        },
        {
            'key': 'missing_servicing_npi',
            'label': 'Missing Servicing Provider NPI',
            'count': missing_servicing,
            'pct': _pct(missing_servicing),
            'severity': 'medium',
            'description': 'Rows missing the servicing provider NPI (a billing NPI may still be present).',
            'impact': 'Without a servicing NPI you cannot verify who actually delivered care, '
                      'weakening fraud detection and quality reporting.',
        },
        {
            'key': 'duplicate_claims',
            'label': 'Duplicate Claim Rows',
            'count': duplicate_rows,
            'pct': _pct(duplicate_rows),
            'severity': 'high',
            'description': 'Rows repeating the same billing NPI, servicing NPI, HCPCS code and month, '
                           'indicating potential duplicate submissions.',
            'impact': 'Duplicate claims lead to double payments — the program pays twice for the '
                      'same service, directly inflating spend and representing recoverable dollars.',
        },
        {
            'key': 'improper_procedure_code',
            'label': 'Invalid / Improper HCPCS Code',
            'count': invalid_hcpcs,
            'pct': _pct(invalid_hcpcs),
            'severity': 'medium',
            'description': 'HCPCS/CPT codes that do not match the expected 5-character format '
                           '(5 digits or a letter followed by 4 digits).',
            'impact': 'An invalid procedure code means the service billed is ambiguous or wrong, '
                      'so payments cannot be validated against fee schedules and may be improper.',
        },
        {
            'key': 'payment_amount_exceeded',
            'label': 'Payment Outlier (per claim line)',
            'count': payment_outliers,
            'pct': _pct(payment_outliers),
            'severity': 'high',
            'description': f'Rows where paid amount per claim line exceeds '
                           f'${PAID_PER_LINE_THRESHOLD:,.0f}, suggesting an overpayment or data error.',
            'impact': 'Per-line payments this large are almost never legitimate for a single '
                      'service — they usually signal an overpayment, keying error, or fraud, and '
                      'are prime recovery targets.',
        },
        {
            'key': 'nonpositive_paid',
            'label': 'Zero / Negative Paid Amount',
            'count': nonpositive_paid,
            'pct': _pct(nonpositive_paid),
            'severity': 'low',
            'description': 'Rows with a total paid amount of zero or less.',
            'impact': 'Zero/negative paid rows distort spend totals and averages and often '
                      'indicate reversals, adjustments, or data-entry errors that need review.',
        },
        {
            'key': 'invalid_month',
            'label': 'Invalid Claim Month',
            'count': invalid_month,
            'pct': _pct(invalid_month),
            'severity': 'low',
            'description': 'Rows whose claim month is missing or not in YYYY-MM format.',
            'impact': 'A missing/invalid date means the claim cannot be placed on a timeline, '
                      'breaking trend analysis and timely-filing checks.',
        },
    ]

    # Attach concrete example rows for drill-down.
    for _issue in issues:
        _issue['examples'] = issue_examples.get(_issue['key'], [])

    total_issue_rows = (missing_both + missing_billing + missing_servicing + duplicate_rows +
                        invalid_hcpcs + payment_outliers + nonpositive_paid + invalid_month)

    top_hcpcs = [
        {
            'code': code,
            'paid': hcpcs_paid.get(code, 0.0),
            'lines': hcpcs_lines.get(code, 0),
        }
        for code in sorted(hcpcs_paid, key=hcpcs_paid.get, reverse=True)[:10]
    ]

    top_providers = [
        {
            'npi': npi,
            'paid': provider_paid.get(npi, 0.0),
            'claims': provider_claims.get(npi, 0),
        }
        for npi in sorted(provider_paid, key=provider_paid.get, reverse=True)[:10]
    ]

    monthly = [
        {'month': m, 'paid': monthly_paid[m], 'lines': monthly_lines[m]}
        for m in sorted(monthly_paid)
    ]

    quality_issue_rows = missing_both + duplicate_rows + invalid_hcpcs + payment_outliers
    clean_pct = round((rows_analyzed - quality_issue_rows) / rows_analyzed * 100, 1) if rows_analyzed else 0.0

    # ---- Financial exposure (dollars at risk from data-quality problems) ----
    # Avoid double counting: cap total exposure at the overall paid amount.
    exposure_total = min(
        exposure_duplicate + exposure_outlier + exposure_missing_npi + exposure_invalid_code,
        total_paid,
    )
    exposure_pct = round(exposure_total / total_paid * 100, 1) if total_paid else 0.0
    exposure_breakdown = [
        {'label': 'Duplicate claim rows', 'amount': exposure_duplicate, 'key': 'duplicate_claims'},
        {'label': 'Payment outliers', 'amount': exposure_outlier, 'key': 'payment_amount_exceeded'},
        {'label': 'Missing provider NPI', 'amount': exposure_missing_npi, 'key': 'null_recipient_values'},
        {'label': 'Invalid HCPCS code', 'amount': exposure_invalid_code, 'key': 'improper_procedure_code'},
    ]
    exposure_breakdown.sort(key=lambda x: x['amount'], reverse=True)

    # ---- Spend concentration (how top-heavy is the spend?) ----
    sorted_provider_paid = sorted(provider_paid.values(), reverse=True)
    n_prov = len(sorted_provider_paid)

    def _top_share(fraction):
        if not n_prov or total_paid <= 0:
            return 0.0
        k = max(1, int(round(n_prov * fraction)))
        return round(sum(sorted_provider_paid[:k]) / total_paid * 100, 1)

    top1_provider_share = _top_share(0.01)
    top10_provider_share = _top_share(0.10)
    top10_count_share = round(min(10, n_prov) / n_prov * 100, 2) if n_prov else 0.0
    top10_dollars = sum(sorted_provider_paid[:10])
    top10_dollars_pct = round(top10_dollars / total_paid * 100, 1) if total_paid else 0.0

    # ---- Year-over-year spend growth ----
    yearly = [
        {'year': y, 'paid': yearly_paid[y]}
        for y in sorted(yearly_paid)
    ]
    for idx, item in enumerate(yearly):
        if idx == 0 or yearly[idx - 1]['paid'] == 0:
            item['yoy_pct'] = None
        else:
            prev = yearly[idx - 1]['paid']
            item['yoy_pct'] = round((item['paid'] - prev) / prev * 100, 1)

    # ---- Highest-risk providers (flagged rows + spend) ----
    high_risk_providers = []
    for npi in sorted(provider_flags, key=provider_flags.get, reverse=True)[:10]:
        claims = provider_claims.get(npi, 0)
        flags = provider_flags[npi]
        high_risk_providers.append({
            'npi': npi,
            'flagged_rows': flags,
            'claims': claims,
            'flag_rate': round(flags / claims * 100, 1) if claims else 0.0,
            'paid': provider_paid.get(npi, 0.0),
            'examples': provider_flag_examples.get(npi, []),
        })

    # ---- Costliest HCPCS codes by average paid-per-line (potential mispricing) ----
    overall_avg_per_line = (total_paid / total_claim_lines) if total_claim_lines else 0.0
    costliest_hcpcs = []
    for code in hcpcs_paid:
        lines_ct = hcpcs_lines.get(code, 0)
        if lines_ct >= 10:  # ignore tiny-volume noise
            avg_pl = hcpcs_paid[code] / lines_ct
            worst = hcpcs_worst_line.get(code)
            costliest_hcpcs.append({
                'code': code,
                'avg_per_line': avg_pl,
                'paid': hcpcs_paid[code],
                'lines': lines_ct,
                # How many times the overall average this code costs per line.
                'vs_avg': round(avg_pl / overall_avg_per_line, 1) if overall_avg_per_line else None,
                'example': worst[1] if worst else None,
            })
    costliest_hcpcs.sort(key=lambda x: x['avg_per_line'], reverse=True)
    costliest_hcpcs = costliest_hcpcs[:10]

    # ---- Category breakdown (compare spend/volume across clinical categories) ----
    categories = []
    for cat in category_paid:
        lines_ct = category_lines.get(cat, 0)
        paid_ct = category_paid[cat]
        categories.append({
            'category': cat,
            'paid': paid_ct,
            'lines': lines_ct,
            'claims': category_claims.get(cat, 0),
            'providers': len(category_providers.get(cat, ())),
            'avg_per_line': (paid_ct / lines_ct) if lines_ct else 0.0,
            'pct_of_paid': round(paid_ct / total_paid * 100, 1) if total_paid else 0.0,
        })
    categories.sort(key=lambda x: x['paid'], reverse=True)

    # ---- Provider peer benchmarking ----
    # For each HCPCS code, treat all billing providers as peers and compare each
    # provider's paid-per-line to the code-wide average. Providers billing far
    # above their peers for the same procedure are potential up-coders/outliers.
    code_provider_count = defaultdict(int)
    for (prov, code) in pc_lines:
        if pc_lines[(prov, code)] >= PEER_MIN_LINES:
            code_provider_count[code] += 1

    peer_outliers = []
    for (prov, code), lines_ct in pc_lines.items():
        if lines_ct < PEER_MIN_LINES:
            continue
        if code_provider_count.get(code, 0) < PEER_MIN_PEERS:
            continue
        code_total_lines = hcpcs_lines.get(code, 0)
        code_total_paid = hcpcs_paid.get(code, 0.0)
        if code_total_lines <= 0 or code_total_paid <= 0:
            continue
        peer_avg = code_total_paid / code_total_lines
        prov_avg = pc_paid[(prov, code)] / lines_ct
        if peer_avg <= 0:
            continue
        ratio = prov_avg / peer_avg
        if ratio >= PEER_OUTLIER_MULTIPLE:
            peer_outliers.append({
                'npi': prov,
                'code': code,
                'category': _hcpcs_category(code),
                'provider_avg': prov_avg,
                'peer_avg': peer_avg,
                'ratio': round(ratio, 1),
                'lines': lines_ct,
                'paid': pc_paid[(prov, code)],
                'peers': code_provider_count.get(code, 0),
            })
    peer_outliers.sort(key=lambda x: x['ratio'], reverse=True)
    peer_outliers = peer_outliers[:15]

    # ---- Optimization: quantify recoverable / avoidable dollars ----
    # 1) Peer-benchmark excess: for every provider-code combo with enough volume,
    #    how much MORE they paid per line than their *peers* (excluding themselves),
    #    i.e. the dollars that would be saved if they billed like the peer group.
    total_peer_excess = 0.0
    peer_excess_by_provider = defaultdict(float)
    for (prov, code), lines_ct in pc_lines.items():
        if lines_ct < PEER_MIN_LINES:
            continue
        if code_provider_count.get(code, 0) < PEER_MIN_PEERS:
            continue
        code_total_lines = hcpcs_lines.get(code, 0)
        code_total_paid = hcpcs_paid.get(code, 0.0)
        other_lines = code_total_lines - lines_ct
        other_paid = code_total_paid - pc_paid[(prov, code)]
        if other_lines <= 0:
            continue
        peer_avg = other_paid / other_lines           # peers only (self excluded)
        prov_avg = pc_paid[(prov, code)] / lines_ct
        if prov_avg > peer_avg:
            excess = (prov_avg - peer_avg) * lines_ct
            total_peer_excess += excess
            peer_excess_by_provider[prov] += excess

    overspend_providers = [
        {
            'npi': npi,
            'excess': peer_excess_by_provider[npi],
            'paid': provider_paid.get(npi, 0.0),
            'claims': provider_claims.get(npi, 0),
            'pct_of_paid': round(peer_excess_by_provider[npi] / provider_paid.get(npi, 0.0) * 100, 1)
            if provider_paid.get(npi, 0.0) else 0.0,
        }
        for npi in sorted(peer_excess_by_provider, key=peer_excess_by_provider.get, reverse=True)[:15]
    ]

    savings_duplicate = exposure_duplicate
    savings_outlier = exposure_outlier
    optimization_potential = savings_duplicate + savings_outlier + total_peer_excess

    def _opt_pct(amount):
        return round(amount / total_paid * 100, 2) if total_paid else 0.0

    optimization_actions = [
        {
            'title': 'Recover duplicate-claim payments',
            'amount': savings_duplicate,
            'pct': _opt_pct(savings_duplicate),
            'severity': 'high',
            'action': 'De-duplicate on (billing NPI, servicing NPI, HCPCS, month) and pursue '
                      'recovery for the repeated payments.',
        },
        {
            'title': 'Review per-line payment outliers',
            'amount': savings_outlier,
            'pct': _opt_pct(savings_outlier),
            'severity': 'high',
            'action': f'Audit claim lines paying over ${PAID_PER_LINE_THRESHOLD:,.0f}/line for '
                      'keying errors, unit errors, or fraud before payment.',
        },
        {
            'title': 'Align overspending providers to peer benchmarks',
            'amount': total_peer_excess,
            'pct': _opt_pct(total_peer_excess),
            'severity': 'medium',
            'action': 'Engage providers billing well above peers for the same codes; renegotiate '
                      'or audit to bring per-line cost toward the peer average.',
        },
    ]
    optimization_actions.sort(key=lambda x: x['amount'], reverse=True)

    # ---- Heatmap: provider (top by spend) x clinical category ----
    provider_cat_paid = defaultdict(float)
    for (prov, code), pd_amount in pc_paid.items():
        provider_cat_paid[(prov, _hcpcs_category(code))] += pd_amount

    hm_providers = [npi for npi, _ in
                    sorted(provider_paid.items(), key=lambda kv: kv[1], reverse=True)[:15]]
    hm_categories = [c['category'] for c in categories[:8]]
    heatmap_rows = []
    heatmap_max = 0.0
    for npi in hm_providers:
        cells = []
        for cat in hm_categories:
            val = provider_cat_paid.get((npi, cat), 0.0)
            if val > heatmap_max:
                heatmap_max = val
            cells.append(val)
        heatmap_rows.append({
            'npi': npi,
            'total': provider_paid.get(npi, 0.0),
            'cells': cells,
        })
    heatmap = {
        'providers': hm_providers,
        'categories': hm_categories,
        'rows': heatmap_rows,
        'max': heatmap_max,
    }

    result = {
        'available': True,
        'file_name': os.path.basename(path),
        'path': path,
        'file_size_human': _human_size(size_bytes),
        'rows_analyzed': rows_analyzed,
        'sample_rows_setting': max_rows,
        'is_sample': rows_analyzed >= max_rows,
        'date_min': date_min,
        'date_max': date_max,
        'total_paid': total_paid,
        'total_patients': total_patients,
        'total_claim_lines': total_claim_lines,
        'avg_paid_per_line': (total_paid / total_claim_lines) if total_claim_lines else 0.0,
        'avg_paid_per_patient': (total_paid / total_patients) if total_patients else 0.0,
        'unique_providers': len(provider_paid),
        'unique_hcpcs': len(hcpcs_paid),
        'issues': issues,
        'total_issue_rows': total_issue_rows,
        'clean_pct': clean_pct,
        'top_hcpcs': top_hcpcs,
        'top_providers': top_providers,
        'monthly': monthly,
        # ---- New customer-focused analytics ----
        'exposure_total': exposure_total,
        'exposure_pct': exposure_pct,
        'exposure_breakdown': exposure_breakdown,
        'top1_provider_share': top1_provider_share,
        'top10_provider_share': top10_provider_share,
        'top10_count_share': top10_count_share,
        'top10_dollars': top10_dollars,
        'top10_dollars_pct': top10_dollars_pct,
        'yearly': yearly,
        'high_risk_providers': high_risk_providers,
        'costliest_hcpcs': costliest_hcpcs,
        'paid_per_line_threshold': PAID_PER_LINE_THRESHOLD,
        'categories': categories,
        'peer_outliers': peer_outliers,
        'peer_outlier_multiple': PEER_OUTLIER_MULTIPLE,
        'peer_min_lines': PEER_MIN_LINES,
        # ---- Optimization view ----
        'optimization_potential': optimization_potential,
        'optimization_pct': _opt_pct(optimization_potential),
        'optimization_actions': optimization_actions,
        'savings_duplicate': savings_duplicate,
        'savings_outlier': savings_outlier,
        'savings_peer_excess': total_peer_excess,
        'overspend_providers': overspend_providers,
        'heatmap': heatmap,
    }

    _CACHE[cache_key] = result
    return result


# Separate cache for the per-entity detail index used by the chatbot. It is kept
# in memory only (never embedded in a page or the /api/claims/data payload).
_DETAIL_CACHE = {}


def build_detail_index(path=None, max_rows=None, force=False):
    """Stream the sample once and build per-NPI and per-HCPCS lookup tables.

    Returns a dict ``{providers: {npi: {...}}, codes: {code: {...}}}`` so the
    chatbot can answer questions about a *specific* provider or procedure code.
    Cached per (path, mtime, max_rows).
    """
    path = path or DEFAULT_CSV_PATH
    max_rows = max_rows or DEFAULT_SAMPLE_ROWS

    if not os.path.exists(path):
        return {'available': False, 'providers': {}, 'codes': {}}

    mtime = os.path.getmtime(path)
    cache_key = (path, mtime, max_rows)
    if not force and cache_key in _DETAIL_CACHE:
        return _DETAIL_CACHE[cache_key]

    providers = {}
    codes = {}
    seen_keys = set()
    month_re = re.compile(r'^\d{4}-\d{2}$')
    rows_analyzed = 0

    with open(path, 'r', newline='', encoding='utf-8', errors='replace') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if rows_analyzed >= max_rows:
                break
            rows_analyzed += 1

            billing = (row.get('BILLING_PROVIDER_NPI_NUM') or '').strip()
            servicing = (row.get('SERVICING_PROVIDER_NPI_NUM') or '').strip()
            hcpcs = (row.get('HCPCS_CODE') or '').strip()
            month = (row.get('CLAIM_FROM_MONTH') or '').strip()
            patients = _to_int(row.get('TOTAL_PATIENTS')) or 0
            lines = _to_int(row.get('TOTAL_CLAIM_LINES')) or 0
            paid = _to_float(row.get('TOTAL_PAID')) or 0.0

            # Replicate the row-level "flagged" logic used by analyze_csv.
            flagged = False
            reasons = []
            if not billing and not servicing:
                flagged = True
                reasons.append('missing provider NPI')
            if not hcpcs or not _HCPCS_RE.match(hcpcs):
                flagged = True
                reasons.append('invalid HCPCS code')
            if lines and paid / lines > PAID_PER_LINE_THRESHOLD:
                flagged = True
                reasons.append('payment outlier')
            dup_key = (billing, servicing, hcpcs, month)
            if dup_key in seen_keys:
                flagged = True
                reasons.append('duplicate row')
            else:
                seen_keys.add(dup_key)

            category = _hcpcs_category(hcpcs) if hcpcs else 'Unknown / Blank'
            provider = billing or servicing

            if provider:
                p = providers.get(provider)
                if p is None:
                    p = {
                        'npi': provider, 'paid': 0.0, 'rows': 0, 'lines': 0,
                        'patients': 0, 'flagged': 0, 'cat_paid': {},
                        'code_paid': {}, 'code_lines': {}, 'months': set(),
                        'example': None,
                    }
                    providers[provider] = p
                p['paid'] += paid
                p['rows'] += 1
                p['lines'] += lines
                p['patients'] += patients
                if flagged:
                    p['flagged'] += 1
                    if p['example'] is None:
                        p['example'] = {
                            'hcpcs': hcpcs, 'month': month, 'lines': lines,
                            'paid': paid, 'reason': ', '.join(reasons),
                        }
                if month_re.match(month):
                    p['months'].add(month)
                if hcpcs:
                    p['cat_paid'][category] = p['cat_paid'].get(category, 0.0) + paid
                    p['code_paid'][hcpcs] = p['code_paid'].get(hcpcs, 0.0) + paid
                    p['code_lines'][hcpcs] = p['code_lines'].get(hcpcs, 0) + lines

            if hcpcs:
                c = codes.get(hcpcs)
                if c is None:
                    c = {
                        'code': hcpcs, 'category': category, 'paid': 0.0,
                        'lines': 0, 'rows': 0, 'providers': set(),
                        'valid': bool(_HCPCS_RE.match(hcpcs)),
                    }
                    codes[hcpcs] = c
                c['paid'] += paid
                c['lines'] += lines
                c['rows'] += 1
                if provider:
                    c['providers'].add(provider)

    # Convert transient sets to counts / lightweight views for JSON safety.
    for p in providers.values():
        p['distinct_months'] = len(p['months'])
        del p['months']
    for c in codes.values():
        c['provider_count'] = len(c['providers'])
        del c['providers']

    index = {'available': True, 'providers': providers, 'codes': codes,
             'rows_analyzed': rows_analyzed}
    _DETAIL_CACHE[cache_key] = index
    return index
