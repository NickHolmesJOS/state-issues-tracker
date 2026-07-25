"""
Rule-based "data chatbot" for the Medicaid claims sample.

There is no external LLM dependency here. Instead the bot is *grounded on the
sample analysis* produced by ``claims_analysis.analyze_csv`` -- that computed
summary of the sampled rows is its entire knowledge base ("trained on the
sample"). Given a natural-language question, it detects intent with keyword
scoring and answers with the real figures from the analysis.
"""

import re


def _money(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = '-' if num < 0 else ''
    num = abs(num)
    for divisor, suffix in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if num >= divisor:
            return f'{sign}${num / divisor:,.2f}{suffix}'
    return f'{sign}${num:,.2f}'


def _num(value):
    try:
        return f'{int(round(float(value))):,}'
    except (TypeError, ValueError):
        return str(value)


# Each intent: (name, keyword list, handler). Handlers take the analysis dict
# and return an answer string. The keyword score = number of matched keywords.
def _suggestions():
    return [
        'How much was paid in total?',
        'Who are the top providers?',
        'What are the biggest overspending providers?',
        'Show me the peer-comparison outliers',
        'How much money is at risk?',
        'What is the optimization potential?',
        'How many duplicate claims are there?',
        'What are the top HCPCS codes?',
        'Which clinical category has the most spend?',
        'What date range does the data cover?',
        'How good is the data quality?',
        'How many rows were analyzed?',
    ]


def _h_total_paid(a):
    return (f"Across the {_num(a.get('rows_analyzed'))} sampled rows, total paid is "
            f"**{_money(a.get('total_paid'))}**, over {_num(a.get('total_claim_lines'))} "
            f"claim lines (avg {_money(a.get('avg_paid_per_line'))}/line) for "
            f"{_num(a.get('total_patients'))} patients.")


def _h_rows(a):
    tail = ' (a bounded sample of the full ~238M-row file)' if a.get('is_sample') else ''
    return (f"I analyzed **{_num(a.get('rows_analyzed'))}** rows{tail}. Each row is a "
            f"pre-aggregated bucket of (billing NPI, servicing NPI, HCPCS code, month).")


def _h_claim_lines(a):
    return (f"The sample sums to **{_num(a.get('total_claim_lines'))}** claim lines. "
            f"That's a column sum of TOTAL_CLAIM_LINES, not a row count -- each row "
            f"already aggregates many underlying claim lines.")


def _h_patients(a):
    return (f"The sample covers **{_num(a.get('total_patients'))}** patients "
            f"(avg {_money(a.get('avg_paid_per_patient'))} paid per patient).")


def _h_top_providers(a):
    rows = a.get('top_providers') or []
    if not rows:
        return "I don't have provider spend data in this sample."
    lines = [f"{i+1}. NPI `{p['npi']}` -- {_money(p['paid'])} across {_num(p['claims'])} claims"
             for i, p in enumerate(rows[:5])]
    return "**Top providers by spend:**\n" + "\n".join(lines)


def _h_top_codes(a):
    rows = a.get('top_hcpcs') or []
    if not rows:
        return "I don't have HCPCS data in this sample."
    lines = [f"{i+1}. `{h['code']}` -- {_money(h['paid'])} ({_num(h['lines'])} lines)"
             for i, h in enumerate(rows[:5])]
    return "**Top HCPCS codes by spend:**\n" + "\n".join(lines)


def _h_costliest(a):
    rows = a.get('costliest_hcpcs') or []
    if not rows:
        return "No costliest-code data in this sample."
    lines = [f"{i+1}. `{h['code']}` -- {_money(h['avg_per_line'])}/line"
             + (f" ({h['vs_avg']}x the sample average)" if h.get('vs_avg') else '')
             for i, h in enumerate(rows[:5])]
    return "**Costliest codes (paid per line):**\n" + "\n".join(lines)


def _h_categories(a):
    rows = a.get('categories') or []
    if not rows:
        return "No category breakdown in this sample."
    lines = [f"{i+1}. {c['category']} -- {_money(c['paid'])} ({c['pct_of_paid']}% of spend)"
             for i, c in enumerate(rows[:5])]
    return "**Spend by clinical category:**\n" + "\n".join(lines)


def _h_peer_outliers(a):
    rows = a.get('peer_outliers') or []
    if not rows:
        return "No peer-comparison outliers were found in this sample."
    p = rows[0]
    lines = [f"{i+1}. NPI `{o['npi']}` bills {o['ratio']}x its peers for code `{o['code']}` "
             f"({_money(o['provider_avg'])} vs {_money(o['peer_avg'])}/line)"
             for i, o in enumerate(rows[:5])]
    return (f"I found **{len(rows)}** peer-comparison outliers (providers billing far above "
            f"peers for the same code). Top ones:\n" + "\n".join(lines))


def _h_overspend(a):
    rows = a.get('overspend_providers') or []
    if not rows:
        return "No above-peer overspending detected in this sample."
    lines = [f"{i+1}. NPI `{o['npi']}` -- {_money(o['excess'])} above peers "
             f"({o['pct_of_paid']}% of its paid)"
             for i, o in enumerate(rows[:5])]
    return ("**Biggest overspending providers vs. peers** (recoverable if aligned to peer "
            "averages):\n" + "\n".join(lines))


def _h_high_risk(a):
    rows = a.get('high_risk_providers') or []
    if not rows:
        return "No high-risk providers flagged in this sample."
    lines = [f"{i+1}. NPI `{p['npi']}` -- {p['flag_rate']}% flag rate "
             f"({_num(p['flagged_rows'])}/{_num(p['claims'])} rows)"
             for i, p in enumerate(rows[:5])]
    return "**Highest-risk providers (data-quality flag rate):**\n" + "\n".join(lines)


def _h_exposure(a):
    parts = a.get('exposure_breakdown') or []
    detail = "; ".join(f"{b['label']}: {_money(b['amount'])}" for b in parts[:4])
    return (f"**{_money(a.get('exposure_total'))}** ({a.get('exposure_pct')}% of paid dollars) "
            f"sits on rows with a data-quality issue. Breakdown -- {detail}.")


def _h_optimization(a):
    return (f"Estimated **{_money(a.get('optimization_potential'))}** "
            f"({a.get('optimization_pct')}% of paid) in optimization potential: "
            f"{_money(a.get('savings_outlier'))} from per-line payment outliers, "
            f"{_money(a.get('savings_peer_excess'))} from above-peer overspending, and "
            f"{_money(a.get('savings_duplicate'))} from duplicate claims. "
            f"See the Optimize page for the action plan.")


def _h_duplicates(a):
    issue = next((i for i in (a.get('issues') or []) if i['key'] == 'duplicate_claims'), None)
    if not issue:
        return "I don't have duplicate-claim data in this sample."
    return (f"**{_num(issue['count'])}** duplicate claim rows ({issue['pct']}% of the sample) -- "
            f"rows repeating the same billing NPI, servicing NPI, HCPCS code and month. "
            f"These risk double payments.")


def _h_missing_npi(a):
    both = next((i for i in (a.get('issues') or []) if i['key'] == 'null_recipient_values'), None)
    bill = next((i for i in (a.get('issues') or []) if i['key'] == 'missing_billing_npi'), None)
    serv = next((i for i in (a.get('issues') or []) if i['key'] == 'missing_servicing_npi'), None)
    return (f"Missing provider NPIs -- both blank: **{_num(both['count']) if both else 0}** "
            f"({both['pct'] if both else 0}%); billing blank: {_num(bill['count']) if bill else 0}; "
            f"servicing blank: {_num(serv['count']) if serv else 0}.")


def _h_dates(a):
    return (f"The sampled data spans **{a.get('date_min') or 'n/a'} to "
            f"{a.get('date_max') or 'n/a'}**.")


def _h_quality(a):
    return (f"About **{a.get('clean_pct')}%** of sampled rows are clean (no major "
            f"data-quality flag). {_num(a.get('total_issue_rows'))} rows have at least one issue "
            f"across {len(a.get('issues') or [])} checked categories.")


def _h_outliers(a):
    issue = next((i for i in (a.get('issues') or []) if i['key'] == 'payment_amount_exceeded'), None)
    thr = a.get('paid_per_line_threshold')
    if not issue:
        return "No payment-outlier data in this sample."
    return (f"**{_num(issue['count'])}** payment outliers ({issue['pct']}%) exceed "
            f"{_money(thr)} paid per claim line -- likely overpayments, unit errors, or fraud.")


_INTENTS = [
    ('help', ['help', 'what can', 'how do', 'ask', 'question', 'examples', 'options'], None),
    ('rows', ['how many rows', 'row count', 'rows analyzed', 'sample size', 'number of rows', 'records'], _h_rows),
    ('claim_lines', ['claim line', 'claim lines', 'total lines', 'how many claims', 'line count'], _h_claim_lines),
    ('patients', ['patient', 'patients', 'people', 'members'], _h_patients),
    ('total_paid', ['total paid', 'how much paid', 'how much was paid', 'paid in total', 'total spend', 'spending', 'total cost', 'how much spent', 'total amount', 'paid overall', 'total dollars'], _h_total_paid),
    ('overspend', ['overspend', 'overspending', 'above peer', 'wasteful', 'spending too much', 'excess'], _h_overspend),
    ('peer', ['peer', 'compare provider', 'up-coding', 'upcoding', 'billing more', 'vs peers', 'outlier provider'], _h_peer_outliers),
    ('high_risk', ['high risk', 'high-risk', 'risky provider', 'flag rate', 'flagged provider', 'suspicious provider'], _h_high_risk),
    ('exposure', ['at risk', 'exposure', 'risk dollars', 'recover', 'recoverable', 'money at risk', 'is at risk', 'money is at risk', 'dollars at risk'], _h_exposure),
    ('optimization', ['optimi', 'saving', 'savings', 'potential', 'reduce', 'cut cost', 'action item', 'opportunity'], _h_optimization),
    ('duplicates', ['duplicate', 'duplicates', 'double pay', 'repeated'], _h_duplicates),
    ('missing_npi', ['missing npi', 'blank npi', 'no npi', 'missing provider', 'null npi', 'missing id'], _h_missing_npi),
    ('outliers', ['payment outlier', 'overpayment', 'too expensive', 'per line outlier', 'expensive line'], _h_outliers),
    ('top_providers', ['top provider', 'biggest provider', 'top npi', 'largest provider', 'who spent', 'top billers'], _h_top_providers),
    ('costliest', ['costliest', 'most expensive code', 'expensive code', 'highest per line', 'mispricing'], _h_costliest),
    ('top_codes', ['top code', 'top hcpcs', 'top procedure', 'common code', 'top cpt', 'procedure code'], _h_top_codes),
    ('categories', ['category', 'categories', 'clinical', 'service type', 'drug', 'surgery', 'radiology', 'breakdown'], _h_categories),
    ('dates', ['date', 'when', 'time range', 'period', 'year', 'years', 'months', 'how far back'], _h_dates),
    ('quality', ['quality', 'clean', 'how good', 'accuracy', 'reliable', 'issues overall'], _h_quality),
]


def _help_text():
    tips = "\n".join(f"- {s}" for s in _suggestions())
    return ("I'm the Claims Data assistant, grounded on the analyzed sample. Ask me things like:\n"
            + tips
            + "\n\nYou can also ask about a specific **NPI** (e.g. \"tell me about NPI 1417262056\"), "
              "a specific **HCPCS code** (e.g. \"code J3490\"), or a specific **issue** "
              "(e.g. \"explain duplicate claims\").")


# ---- Entity detection ----
_NPI_RE = re.compile(r'\b(\d{7,10})\b')
_CODE_RE = re.compile(r'\b([A-Za-z]\d{4})\b')
_CODE_HINT_RE = re.compile(r'\b(?:code|hcpcs|cpt|procedure)\s+([A-Za-z]?\d{1,5})\b')

# Issue keyword -> issue key, for "explain <issue>" style questions.
_ISSUE_KEYWORDS = {
    'duplicate': 'duplicate_claims',
    'missing provider': 'null_recipient_values',
    'both blank': 'null_recipient_values',
    'missing billing': 'missing_billing_npi',
    'missing servicing': 'missing_servicing_npi',
    'invalid hcpcs': 'improper_procedure_code',
    'improper': 'improper_procedure_code',
    'invalid code': 'improper_procedure_code',
    'payment outlier': 'payment_amount_exceeded',
    'overpayment': 'payment_amount_exceeded',
    'payment amount': 'payment_amount_exceeded',
    'negative paid': 'nonpositive_paid',
    'zero paid': 'nonpositive_paid',
    'non-positive': 'nonpositive_paid',
    'invalid month': 'invalid_month',
    'invalid date': 'invalid_month',
}


def _top_items(mapping, n=5):
    return sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)[:n]


def _answer_npi(npi, analysis, detail):
    prov = (detail or {}).get('providers', {}).get(npi)
    if not prov:
        return (f"I couldn't find NPI `{npi}` in the analyzed sample of "
                f"{_num((detail or {}).get('rows_analyzed', 0))} rows. It may fall outside the "
                f"current sample -- try increasing the sample size on the page.")
    flag_rate = round(prov['flagged'] / prov['rows'] * 100, 1) if prov['rows'] else 0.0
    avg_line = prov['paid'] / prov['lines'] if prov['lines'] else 0.0
    lines = [
        f"**Provider NPI `{npi}`** (from the sample):",
        f"- Total paid: {_money(prov['paid'])} across {_num(prov['rows'])} rows / "
        f"{_num(prov['lines'])} claim lines ({_money(avg_line)}/line)",
        f"- Patients: {_num(prov['patients'])}  ·  Active months: {_num(prov.get('distinct_months', 0))}",
        f"- Data-quality flags: {_num(prov['flagged'])} rows ({flag_rate}% flag rate)",
    ]
    top_cats = _top_items(prov['cat_paid'], 3)
    if top_cats:
        lines.append("- Top categories: " + "; ".join(f"{c} ({_money(v)})" for c, v in top_cats))
    top_codes = _top_items(prov['code_paid'], 3)
    if top_codes:
        lines.append("- Top codes: " + "; ".join(f"`{c}` ({_money(v)})" for c, v in top_codes))
    if prov.get('example'):
        ex = prov['example']
        lines.append(f"- Example flagged row: code `{ex['hcpcs'] or 'blank'}`, {ex['month'] or 'n/a'}, "
                     f"{_num(ex['lines'])} lines, {_money(ex['paid'])} -- {ex['reason']}.")
    # Cross-reference the ranked lists in the analysis.
    notes = []
    for o in (analysis.get('peer_outliers') or []):
        if o['npi'] == npi:
            notes.append(f"flagged as a peer outlier ({o['ratio']}x peers on code `{o['code']}`)")
            break
    for o in (analysis.get('overspend_providers') or []):
        if o['npi'] == npi:
            notes.append(f"among the biggest overspenders ({_money(o['excess'])} above peers)")
            break
    if notes:
        lines.append("- Note: this provider is " + " and ".join(notes) + ".")
    return "\n".join(lines)


def _answer_code(code, analysis, detail):
    codes = (detail or {}).get('codes', {})
    entry = codes.get(code) or codes.get(code.upper())
    if not entry:
        return (f"I couldn't find HCPCS code `{code}` in the analyzed sample. Try increasing the "
                f"sample size, or double-check the code.")
    avg_line = entry['paid'] / entry['lines'] if entry['lines'] else 0.0
    valid = 'valid' if entry.get('valid') else '**invalid format**'
    lines = [
        f"**HCPCS code `{entry['code']}`** ({entry['category']}, {valid}):",
        f"- Total paid: {_money(entry['paid'])} across {_num(entry['lines'])} claim lines "
        f"({_money(avg_line)}/line)",
        f"- Billed by {_num(entry['provider_count'])} distinct providers over {_num(entry['rows'])} rows",
    ]
    overall = analysis.get('avg_paid_per_line') or 0.0
    if overall > 0:
        lines.append(f"- That's {round(avg_line / overall, 1)}x the sample-wide average of "
                     f"{_money(overall)}/line.")
    return "\n".join(lines)


def _answer_issue(issue_key, analysis):
    issue = next((i for i in (analysis.get('issues') or []) if i['key'] == issue_key), None)
    if not issue:
        return "I don't have data on that specific issue in this sample."
    lines = [
        f"**{issue['label']}** ({issue['severity']} severity):",
        f"- Count: {_num(issue['count'])} rows ({issue['pct']}% of the sample)",
        f"- What it is: {issue['description']}",
        f"- Why it matters: {issue.get('impact', 'n/a')}",
    ]
    ex = (issue.get('examples') or [])
    if ex:
        e = ex[0]
        lines.append(f"- Example: billing `{e.get('billing') or 'blank'}`, servicing "
                     f"`{e.get('servicing') or 'blank'}`, code `{e.get('hcpcs') or 'blank'}`, "
                     f"{e.get('month') or 'n/a'} -- {e.get('reason', '')}")
    return "\n".join(lines)


def answer_question(question, analysis, detail=None):
    """Return a dict: {answer, intent, suggestions} for a question over the sample.

    ``detail`` is the optional per-entity index from
    ``claims_analysis.build_detail_index`` used for NPI/code lookups.
    """
    if not analysis or not analysis.get('available'):
        return {
            'answer': "The claims CSV isn't available, so I have no sample data to answer from.",
            'intent': 'unavailable',
            'suggestions': [],
        }

    q = (question or '').strip().lower()
    if not q:
        return {'answer': _help_text(), 'intent': 'help', 'suggestions': _suggestions()}

    # Greeting shortcut.
    if re.fullmatch(r'(hi|hey|hello|yo|sup|hiya)[!. ]*', q):
        return {
            'answer': "Hi! I can answer questions about the analyzed claims sample. "
                      "Ask about totals, top providers, a specific NPI, an HCPCS code, or an issue.",
            'intent': 'greeting',
            'suggestions': _suggestions(),
        }

    # ---- Entity lookups take priority over general intents ----
    # Specific issue explanation ("explain/tell me about <issue>").
    if any(w in q for w in ('explain', 'tell me about', 'what is', 'what are', 'describe', 'about the')):
        for kw, key in _ISSUE_KEYWORDS.items():
            if kw in q:
                return {'answer': _answer_issue(key, analysis), 'intent': 'issue_detail',
                        'suggestions': _suggestions()[:4]}

    # Specific HCPCS code (letter + 4 digits, or "code XXXX" hint).
    code_match = _CODE_RE.search(question or '') or _CODE_HINT_RE.search(q)
    if code_match and ('code' in q or 'hcpcs' in q or 'cpt' in q or 'procedure' in q
                       or _CODE_RE.search(question or '')):
        return {'answer': _answer_code(code_match.group(1).upper(), analysis, detail),
                'intent': 'code_lookup', 'suggestions': _suggestions()[:4]}

    # Specific NPI (7-10 digit number).
    npi_match = _NPI_RE.search(q)
    if npi_match:
        return {'answer': _answer_npi(npi_match.group(1), analysis, detail),
                'intent': 'npi_lookup', 'suggestions': _suggestions()[:4]}

    # Score intents by number of matched keywords (longer phrases weigh more).
    best_name, best_handler, best_score = None, None, 0
    for name, keywords, handler in _INTENTS:
        score = 0
        for kw in keywords:
            if kw in q:
                score += 1 + kw.count(' ')  # multi-word phrases score higher
        if score > best_score:
            best_name, best_handler, best_score = name, handler, score

    if best_score == 0 or best_name == 'help':
        return {'answer': _help_text(), 'intent': 'help', 'suggestions': _suggestions()}

    try:
        answer = best_handler(analysis)
    except Exception:
        answer = _help_text()
        best_name = 'help'

    return {'answer': answer, 'intent': best_name, 'suggestions': _suggestions()[:4]}
