from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime
import sqlite3
import os
from collections import Counter
import re

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'issues.db')
app.config['DATABASE'] = os.environ.get('DATABASE_PATH', DEFAULT_DB_PATH)

ALL_STATES = [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware',
    'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky',
    'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi',
    'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey', 'New Mexico',
    'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania',
    'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont',
    'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming'
]

CMS_ISSUE_TYPES = [
    'duplicate_claims',
    'invalid_diagnosis_code',
    'debit_credit_mismatch',
    'null_recipient_values',
    'improper_procedure_code',
    'referential_integrity',
    'payment_amount_exceeded',
    'birth_date_error',
    'discharge_date_error'
]
ISSUE_TYPES = CMS_ISSUE_TYPES  # backward compatibility

STATE_ABBR = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
    'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
    'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA',
    'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT',
    'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
    'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
    'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT',
    'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'
}

CMS_ISSUE_TITLES = {
    'duplicate_claims': 'Duplicate Claims Issue',
    'invalid_diagnosis_code': 'Invalid Diagnosis Code',
    'debit_credit_mismatch': 'Debit/Credit Not Matching',
    'null_recipient_values': 'Null Recipient Values',
    'improper_procedure_code': 'Improper Population of Value in Procedure Code Column',
    'referential_integrity': 'Referential Integrity Issue',
    'payment_amount_exceeded': 'Claim Payment Amount Exceeds Max for Type of Service',
    'birth_date_error': 'Birth Date Greater Than Claim Date of Service',
    'discharge_date_error': 'Discharge Date Greater Than Claim Admission Date'
}

# Duplicate claim rate (%) per state, ordered to match ALL_STATES alphabetical order
DUP_CLAIM_RATES = [
    1.2, 3.4, 0.8, 5.1, 2.3, 4.7, 1.9, 6.2, 0.5, 3.8,
    2.1, 4.3, 1.5, 7.2, 2.8, 3.1, 0.9, 5.5, 1.7, 4.1,
    2.6, 3.9, 1.1, 6.8, 2.4, 0.7, 3.6, 2.9, 4.8, 1.3,
    5.9, 2.2, 1.6, 3.3, 0.6, 4.5, 2.7, 1.8, 5.3, 3.7,
    2.0, 6.1, 1.4, 4.2, 0.4, 3.5, 2.5, 7.8, 1.0, 4.9
]

# Base instance count per quarter for each non-duplicate issue type
CMS_BASE_COUNTS = {
    'invalid_diagnosis_code': 145,
    'debit_credit_mismatch': 12,
    'null_recipient_values': 78,
    'improper_procedure_code': 234,
    'referential_integrity': 34,
    'payment_amount_exceeded': 23,
    'birth_date_error': 5,
    'discharge_date_error': 8
}

CMS_ISSUE_DESCRIPTIONS = {
    'duplicate_claims': [
        'Duplicate claim submissions detected in current period. Exact duplicates with matching NPI, service date, procedure code, and billed amount found across claims batch.',
        'Near-duplicate claims identified where minor field variations mask resubmissions. Member ID, DOS, and procedure code match across multiple claim IDs.',
        'Prior authorization duplicates found; same service authorized and billed under distinct claim IDs within the same benefit period.'
    ],
    'invalid_diagnosis_code': [
        'ICD-10-CM codes submitted that are not valid for the date of service. Codes are retired or do not exist in the applicable code set version.',
        'Diagnosis codes missing required 4th, 5th, or 6th character specificity per ICD-10-CM official guidelines for the billed service.',
        'Principal diagnosis code sequenced as a manifestation code, which cannot be listed first per ICD-10-CM coding conventions.'
    ],
    'debit_credit_mismatch': [
        'Remittance advice shows debit and credit totals that do not reconcile with paid claim amounts in the system of record.',
        'Encounter data financial crosswalk shows discrepancy between capitation payments and adjudicated claim values for the period.',
        'Monthly financial reconciliation identified net balance discrepancy between claim payment ledger and treasury disbursement records.'
    ],
    'null_recipient_values': [
        'Medicaid ID field is null or blank on submitted claims, preventing member attribution and eligibility validation.',
        'Recipient date of birth and gender fields contain null values, blocking downstream clinical quality measure attribution.',
        'Member enrollment segment contains null values in required demographic fields, causing eligibility verification failures.'
    ],
    'improper_procedure_code': [
        'Procedure code column populated with revenue codes instead of HCPCS/CPT codes, causing systematic claim adjudication failures.',
        'Type of Bill code used in place of procedure code on professional claims, resulting in systematic processing errors.',
        'Procedure modifier applied in the procedure code field rather than the designated modifier field, causing pricing calculation errors.'
    ],
    'referential_integrity': [
        'Claim header references a provider NPI that does not exist in the provider enrollment file, violating referential constraints.',
        'Member ID on claim does not match any active enrollment record, indicating breakdown between claims and eligibility systems.',
        'Rendering provider taxonomy code does not correspond to a valid taxonomy in the reference table, blocking credentialing validation.'
    ],
    'payment_amount_exceeded': [
        'Claim payment amount exceeds the established fee schedule maximum allowable for the billed procedure and place of service.',
        'Inpatient DRG payment calculation resulted in an amount exceeding the outlier threshold, requiring additional clinical review.',
        'Bundled payment for episode of care surpasses the benchmark rate set for the applicable service category and region.'
    ],
    'birth_date_error': [
        'Member date of birth on claim is recorded as a date after the claim date of service, indicating a data entry or system error.',
        'Newborn claims contain birth date that post-dates the delivery admission date of service in the ADT feed.',
        'Eligibility file shows member birth date greater than the earliest claim date in history, creating an impossible chronological sequence.'
    ],
    'discharge_date_error': [
        'Inpatient claim discharge date precedes the admission date, indicating a systemic date reversal error in the ADT feed.',
        'Long-term care claims show discharge date earlier than the admission date on the claim header record.',
        'UB-04 inpatient claims submitted with statement-from and statement-through dates transposed, resulting in negative length of stay.'
    ]
}

def get_db():
    """Get database connection"""
    db_path = app.config['DATABASE']
    db_dir = os.path.dirname(db_path)
    if db_dir:
        try:
            os.makedirs(db_dir, exist_ok=True)
        except PermissionError:
            # Configured path not writable; fall back to a local path next to app.py
            db_path = os.path.join(BASE_DIR, 'issues.db')
            app.config['DATABASE'] = db_path
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Initialize database with schema"""
    db = get_db()
    cursor = db.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'medium',
            issue_type TEXT DEFAULT 'general',
            metric_value REAL DEFAULT NULL,
            start_date TEXT DEFAULT NULL,
            end_date TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (state_id) REFERENCES states(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS issue_tags (
            issue_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            FOREIGN KEY (issue_id) REFERENCES issues(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id),
            PRIMARY KEY (issue_id, tag_id)
        )
    ''')

    # Migration: ensure issue_type column exists
    cursor.execute("PRAGMA table_info(issues)")
    issue_columns = [row[1] for row in cursor.fetchall()]
    if 'issue_type' not in issue_columns:
        cursor.execute("ALTER TABLE issues ADD COLUMN issue_type TEXT DEFAULT 'general'")
    if 'metric_value' not in issue_columns:
        cursor.execute('ALTER TABLE issues ADD COLUMN metric_value REAL DEFAULT NULL')
    if 'start_date' not in issue_columns:
        cursor.execute('ALTER TABLE issues ADD COLUMN start_date TEXT DEFAULT NULL')
    if 'end_date' not in issue_columns:
        cursor.execute('ALTER TABLE issues ADD COLUMN end_date TEXT DEFAULT NULL')

    # Ensure all states and tags exist
    for state in ALL_STATES:
        cursor.execute('INSERT OR IGNORE INTO states (name) VALUES (?)', (state,))

    tags = ['needs improvement', 'will probably benefit', 'will not benefit', 'urgent', 'completed', 'in progress']
    for tag in tags:
        cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag,))

    db.commit()

    # ── CMS Variance Seeding ──────────────────────────────────────────────────
    STATE_PROFILES = [
        0, 2, 0, 3, 1, 3, 1, 4, 0, 2,  # AL AK AZ AR CA CO CT DE FL GA
        1, 3, 0, 4, 1, 2, 0, 3, 1, 2,  # HI ID IL IN IA KS KY LA ME MD
        1, 2, 0, 4, 1, 0, 2, 1, 3, 0,  # MA MI MN MS MO MT NE NV NH NJ
        3, 1, 1, 2, 0, 3, 1, 1, 3, 2,  # NM NY NC ND OH OK OR PA RI SC
        1, 4, 0, 2, 0, 2, 1, 4, 0, 3   # SD TN TX UT VT VA WA WV WI WY
    ]
    PROFILE_TOTALS = [18, 40, 66, 96, 142]
    PROFILE_STATUS_DIST = [
        (0.10, 0.82, 0.08),
        (0.20, 0.70, 0.10),
        (0.40, 0.45, 0.15),
        (0.62, 0.26, 0.12),
        (0.76, 0.14, 0.10),
    ]
    NON_DUP_TYPES = [t for t in CMS_ISSUE_TYPES if t != 'duplicate_claims']
    from datetime import date as _date, timedelta as _td
    QUARTERS = [
        ('Q2 2025', _date(2025, 4, 1),  91),
        ('Q3 2025', _date(2025, 7, 1),  92),
        ('Q4 2025', _date(2025, 10, 1), 92),
        ('Q1 2026', _date(2026, 1, 1),  90),
    ]

    def _h(a, b=0, c=0):
        return (a * 37 + b * 23 + c * 13 + a * b + b * c + 1) % 100

    cursor.execute("SELECT COUNT(*) FROM issues WHERE issue_type = 'duplicate_claims'")
    cms_seeded = cursor.fetchone()[0] > 0

    if not cms_seeded:
        cursor.execute('DELETE FROM issue_tags')
        cursor.execute('DELETE FROM issues')
        cursor.execute('SELECT id, name FROM states ORDER BY name')
        state_rows = cursor.fetchall()
        cursor.execute('SELECT id, name FROM tags ORDER BY id')
        tag_rows = cursor.fetchall()
        tag_lookup = {row['name']: row['id'] for row in tag_rows}

        for state_idx, state_row in enumerate(state_rows):
            state_id   = state_row['id']
            state_name = state_row['name']
            profile    = STATE_PROFILES[state_idx]
            dup_rate   = DUP_CLAIM_RATES[state_idx]

            base_total   = PROFILE_TOTALS[profile]
            var_frac     = (_h(state_idx, 7) - 50) / 100.0
            total_issues = max(10, int(round(base_total * (1 + var_frac * 0.4))))
            non_dup_total = max(8, total_issues - len(QUARTERS))

            weights = [0.5 + _h(state_idx, ti, 3) / 100.0 * 3.0
                       for ti in range(len(NON_DUP_TYPES))]
            total_w = sum(weights)
            type_counts = [max(1, round(w / total_w * non_dup_total)) for w in weights]
            diff = non_dup_total - sum(type_counts)
            for i in range(abs(diff)):
                idx_adj = i % len(type_counts)
                type_counts[idx_adj] += (
                    1 if diff > 0 else (-1 if type_counts[idx_adj] > 1 else 0))

            open_p, done_p, canc_p = PROFILE_STATUS_DIST[profile]

            for qi, (qlabel, qstart, qlen) in enumerate(QUARTERS):
                sd_off = _h(state_idx, qi) % min(20, qlen // 4)
                sd = qstart + _td(days=sd_off)
                status = 'open' if qi == len(QUARTERS) - 1 else 'done'
                if status == 'done':
                    ed = sd + _td(days=20 + _h(state_idx, qi, 1) % 40)
                else:
                    ed = None
                metric = max(0.1, min(9.9,
                    round(dup_rate + (_h(state_idx, qi, 2) - 50) / 500.0, 2)))
                title = (state_name + ' – ' +
                         CMS_ISSUE_TITLES['duplicate_claims'] +
                         ' (' + qlabel + ')')
                desc  = CMS_ISSUE_DESCRIPTIONS['duplicate_claims'][
                            (qi + state_idx) % 3]
                prio  = 'high' if dup_rate > 4.0 else 'medium'
                cursor.execute(
                    'INSERT INTO issues '
                    '(state_id, title, description, status, priority, issue_type,'
                    ' metric_value, start_date, end_date) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (state_id, title, desc, status, prio, 'duplicate_claims',
                     metric,
                     sd.strftime('%Y-%m-%d'),
                     ed.strftime('%Y-%m-%d') if ed else None))
                iid = cursor.lastrowid
                for tname in (['completed', 'will probably benefit']
                               if status == 'done' else
                               ['needs improvement', 'in progress', 'urgent']):
                    tid = tag_lookup.get(tname)
                    if tid:
                        cursor.execute(
                            'INSERT OR IGNORE INTO issue_tags VALUES (?, ?)',
                            (iid, tid))

            for ti, issue_type in enumerate(NON_DUP_TYPES):
                n = type_counts[ti]
                for k in range(n):
                    qi = _h(state_idx, ti, k + 5) % len(QUARTERS)
                    qlabel, qstart, qlen = QUARTERS[qi]
                    label = CMS_ISSUE_TITLES[issue_type]
                    title = (state_name + ' – ' + label +
                             (' (' + qlabel + ')' if n <= 1 else
                              ' #' + str(k + 1) + ' (' + qlabel + ')'))
                    desc = CMS_ISSUE_DESCRIPTIONS[issue_type][
                               (ti + k + state_idx) % 3]
                    metric_val = round(
                        CMS_BASE_COUNTS[issue_type] *
                        (0.25 + _h(state_idx, ti, k + 1) / 100.0 * 2.75))
                    rnd = _h(state_idx, ti * 100 + k + 9) % 100
                    if rnd < int(done_p * 100):
                        status = 'done'
                    elif rnd < int((done_p + canc_p) * 100):
                        status = 'cancelled'
                    else:
                        status = 'open'
                    priority = ['low', 'medium', 'high', 'medium', 'high'][
                                   _h(state_idx, ti, k + 2) % 5]
                    sd_off = _h(state_idx, ti, k + 3) % min(40, qlen // 2)
                    sd = qstart + _td(days=sd_off)
                    if status in ('done', 'cancelled'):
                        work_days = (14 + _h(state_idx, ti, k + 4) % 77
                                     if status == 'done' else
                                     7 + _h(state_idx, ti, k + 4) % 42)
                        ed = sd + _td(days=work_days)
                    else:
                        ed = None
                    cursor.execute(
                        'INSERT INTO issues '
                        '(state_id, title, description, status, priority,'
                        ' issue_type, metric_value, start_date, end_date) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (state_id, title, desc, status, priority, issue_type,
                         metric_val,
                         sd.strftime('%Y-%m-%d'),
                         ed.strftime('%Y-%m-%d') if ed else None))
                    iid = cursor.lastrowid
                    if status == 'done':
                        tnames = ['completed', 'will probably benefit',
                                  'in progress']
                    elif status == 'cancelled':
                        tnames = ['will not benefit', 'in progress']
                    else:
                        tnames = (['needs improvement', 'in progress', 'urgent']
                                  if priority == 'high' else
                                  ['needs improvement', 'will probably benefit',
                                   'in progress'])
                    for tname in tnames:
                        tid = tag_lookup.get(tname)
                        if tid:
                            cursor.execute(
                                'INSERT OR IGNORE INTO issue_tags VALUES (?, ?)',
                                (iid, tid))

    db.commit()
    db.close()

@app.route('/')
def dashboard():
    """Main dashboard showing overview"""
    db = get_db()
    cursor = db.cursor()
    
    # Get all states with issue counts
    cursor.execute('''
        SELECT s.id, s.name, 
               COUNT(i.id) as total_issues,
               SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) as done_issues,
               SUM(CASE WHEN i.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_issues,
               SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open_issues
        FROM states s
        LEFT JOIN issues i ON s.id = i.state_id
        GROUP BY s.id, s.name
        ORDER BY s.name
    ''')
    
    states = cursor.fetchall()
    db.close()

    all_rows = get_comparison_rows()
    leaderboard = sorted(
        [r for r in all_rows if (r.get('total') or 0) > 0],
        key=lambda x: x.get('composite_score', 0), reverse=True
    )[:10]

    total_issues = sum((r['total_issues'] or 0) for r in states)
    done_issues  = sum((r['done_issues'] or 0) for r in states)
    open_issues  = sum((r['open_issues'] or 0) for r in states)

    return render_template('dashboard.html', states=states, leaderboard=leaderboard,
                           total_issues=total_issues, done_issues=done_issues,
                           open_issues=open_issues)

@app.route('/state/<int:state_id>')
def state_detail(state_id):
    """Detailed view of a specific state's issues"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT * FROM states WHERE id = ?', (state_id,))
    state = cursor.fetchone()
    
    if not state:
        return redirect(url_for('dashboard'))
    
    cursor.execute('''
        SELECT i.*, GROUP_CONCAT(t.name, ', ') as tags
        FROM issues i
        LEFT JOIN issue_tags it ON i.id = it.issue_id
        LEFT JOIN tags t ON it.tag_id = t.id
        WHERE i.state_id = ?
        GROUP BY i.id
        ORDER BY i.created_at DESC
    ''', (state_id,))
    
    raw_issues = cursor.fetchall()

    cursor.execute('SELECT DISTINCT issue_type FROM issues ORDER BY issue_type')
    issue_types = [row[0] for row in cursor.fetchall() if row[0]]

    db.close()

    now = datetime.utcnow()
    issues = []
    for row in raw_issues:
        item = dict(row)
        if item.get('status') == 'open' and item.get('created_at'):
            try:
                created = datetime.strptime(item['created_at'][:19], '%Y-%m-%d %H:%M:%S')
                item['days_open'] = (now - created).days
            except Exception:
                item['days_open'] = None
        else:
            item['days_open'] = None
        issues.append(item)

    return render_template('state_detail.html', state=state, issues=issues, issue_types=issue_types)

@app.route('/state/<int:state_id>/issue/new', methods=['POST'])
def create_issue(state_id):
    """Create a custom issue for a state"""
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    status = (request.form.get('status') or 'open').strip().lower()
    priority = (request.form.get('priority') or 'medium').strip().lower()
    issue_type = (request.form.get('issue_type') or 'general').strip().lower()

    allowed_statuses = {'open', 'done', 'cancelled'}
    allowed_priorities = {'low', 'medium', 'high'}

    if not title:
        return redirect(url_for('state_detail', state_id=state_id))

    if status not in allowed_statuses:
        status = 'open'
    if priority not in allowed_priorities:
        priority = 'medium'
    if not issue_type:
        issue_type = 'general'

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id FROM states WHERE id = ?', (state_id,))
    if not cursor.fetchone():
        db.close()
        return redirect(url_for('dashboard'))

    cursor.execute('''
        INSERT INTO issues (state_id, title, description, status, priority, issue_type)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (state_id, title, description, status, priority, issue_type))

    db.commit()
    db.close()

    return redirect(url_for('state_detail', state_id=state_id))

@app.route('/compare')
def compare():
    """Compare issues across states"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id, name FROM states ORDER BY name')
    states = cursor.fetchall()
    
    cursor.execute('SELECT id, name FROM tags ORDER BY name')
    tags = cursor.fetchall()
    
    db.close()
    
    return render_template('compare.html', states=states, tags=tags)

@app.route('/api/compare')
def api_compare():
    """API endpoint for comparison data"""
    tag_id = request.args.get('tag_id', type=int)
    
    db = get_db()
    cursor = db.cursor()
    
    if tag_id:
        cursor.execute('''
            SELECT s.name as state, 
                   COUNT(DISTINCT i.id) as total,
                   SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) as successful,
                   SUM(CASE WHEN i.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                   SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open
            FROM states s
            LEFT JOIN issues i ON s.id = i.state_id
            LEFT JOIN issue_tags it ON i.id = it.issue_id
            WHERE it.tag_id = ?
            GROUP BY s.id, s.name
            ORDER BY successful DESC, s.name
        ''', (tag_id,))
    else:
        cursor.execute('''
            SELECT s.name as state, 
                   COUNT(i.id) as total,
                   SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) as successful,
                   SUM(CASE WHEN i.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                   SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open
            FROM states s
            LEFT JOIN issues i ON s.id = i.state_id
            GROUP BY s.id, s.name
            ORDER BY s.name
        ''')
    
    results = cursor.fetchall()
    db.close()
    
    data = [dict(row) for row in results]
    return jsonify(data)

@app.route('/api/issue/<int:issue_id>/update', methods=['POST'])
def update_issue(issue_id):
    """Update issue status"""
    data = request.json
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        UPDATE issues 
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (data.get('status'), issue_id))
    
    db.commit()
    db.close()
    
    return jsonify({'success': True})

@app.route('/analytics')
def analytics():
    """Analytics and insights page"""
    db = get_db()
    cursor = db.cursor()
    
    # Get overall statistics
    cursor.execute('''
        SELECT COUNT(*) as total_issues,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open,
               SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
        FROM issues
    ''')
    
    stats = dict(cursor.fetchone())
    
    # Get tag statistics
    cursor.execute('''
        SELECT t.name, COUNT(it.issue_id) as count
        FROM tags t
        LEFT JOIN issue_tags it ON t.id = it.tag_id
        GROUP BY t.id, t.name
        ORDER BY count DESC
    ''')
    
    tag_stats = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT issue_type,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open,
               SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
        FROM issues
        WHERE issue_type IS NOT NULL AND issue_type != ''
        GROUP BY issue_type
        ORDER BY total DESC
        LIMIT 12
    ''')
    issue_type_stats = [dict(row) for row in cursor.fetchall()]

    db.close()

    return render_template('analytics.html', stats=stats, tag_stats=tag_stats, issue_type_stats=issue_type_stats)

@app.route('/ai-insights')
def ai_insights():
    """AI-powered insights and recommendations"""
    db = get_db()
    cursor = db.cursor()
    
    # Get all states with their metrics
    cursor.execute('''
        SELECT s.id, s.name, 
               COUNT(i.id) as total_issues,
               SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) as done_issues,
               SUM(CASE WHEN i.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_issues,
               SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open_issues
        FROM states s
        LEFT JOIN issues i ON s.id = i.state_id
        GROUP BY s.id, s.name
        ORDER BY s.name
    ''')
    
    states_data = [dict(row) for row in cursor.fetchall()]
    
    # Get issue types
    cursor.execute('SELECT DISTINCT issue_type FROM issues ORDER BY issue_type')
    issue_types = [row[0] for row in cursor.fetchall()]
    
    db.close()
    
    return render_template('ai_insights.html', states_data=states_data, issue_types=issue_types)

@app.route('/api/ai-comparison')
def api_ai_comparison():
    """AI comparison endpoint"""
    issue_type = (request.args.get('issue_type') or '').strip().lower()
    state_ids = [s for s in (request.args.get('states') or '').split(',') if s.strip()]
    min_total = request.args.get('min_total', type=int)
    if min_total is None:
        min_total = 3
    min_total = max(0, min_total)

    data = get_comparison_rows(issue_type=issue_type, state_ids=state_ids)
    filtered = [d for d in data if (d.get('total') or 0) >= min_total]
    insights = generate_ai_insights(filtered, issue_type)

    states_with_data = sum(1 for d in data if (d.get('total') or 0) > 0)
    avg_success = (sum(d.get('success_rate', 0) for d in filtered) / len(filtered)) if filtered else 0.0
    avg_confidence = (sum(d.get('confidence', 0) for d in filtered) / len(filtered)) if filtered else 0.0

    meta = {
        'total_states': len(data),
        'states_with_data': states_with_data,
        'states_analyzed': len(filtered),
        'min_total': min_total,
        'avg_success_rate': round(avg_success, 1),
        'avg_confidence': round(avg_confidence, 1)
    }

    return jsonify({'data': filtered, 'insights': insights, 'meta': meta})

def get_comparison_rows(issue_type='', state_ids=None):
    """Build consistent comparison rows with quality metrics"""
    db = get_db()
    cursor = db.cursor()

    params = [issue_type, issue_type]
    where_clause = ''
    if state_ids:
        placeholders = ','.join(['?' for _ in state_ids])
        where_clause = f'WHERE s.id IN ({placeholders})'
        params.extend(state_ids)

    cursor.execute(f'''
        SELECT s.id,
               s.name as state,
               COUNT(i.id) as total,
               SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) as successful,
               SUM(CASE WHEN i.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
               SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open
        FROM states s
        LEFT JOIN issues i
            ON s.id = i.state_id
           AND (? = '' OR LOWER(i.issue_type) = ?)
        {where_clause}
        GROUP BY s.id, s.name
        ORDER BY s.name
    ''', params)

    rows = []
    for row in cursor.fetchall():
        item = dict(row)
        total = item['total'] or 0
        successful = item['successful'] or 0
        cancelled = item['cancelled'] or 0
        open_count = item['open'] or 0

        success_rate = (successful / total * 100.0) if total > 0 else 0.0
        cancel_rate = (cancelled / total * 100.0) if total > 0 else 0.0
        backlog_rate = (open_count / total * 100.0) if total > 0 else 0.0
        confidence = min(1.0, total / 6.0)
        composite_score = (
            (0.55 * success_rate) +
            (0.25 * (100.0 - cancel_rate)) +
            (0.20 * (100.0 - backlog_rate))
        ) * confidence

        item.update({
            'success_rate': round(success_rate, 1),
            'cancel_rate': round(cancel_rate, 1),
            'backlog_rate': round(backlog_rate, 1),
            'confidence': round(confidence * 100, 1),
            'composite_score': round(composite_score, 1)
        })
        rows.append(item)

    db.close()
    return rows


def build_executive_brief(issue_type='', min_total=3):
    """Build an executive-ready quality brief payload"""
    rows = get_comparison_rows(issue_type=issue_type)
    eligible = [r for r in rows if (r.get('total') or 0) >= max(0, min_total)]

    if not eligible:
        return {
            'kpis': {
                'states_analyzed': 0,
                'avg_success': 0.0,
                'avg_backlog': 0.0,
                'avg_quality': 0.0,
                'coverage': 0.0
            },
            'top_states': [],
            'watchlist': [],
            'summary': 'Insufficient data for the selected filters.',
            'actions_30_60_90': {
                '30_days': ['Widen filters or lower minimum sample threshold.'],
                '60_days': ['Standardize issue categorization for better comparability.'],
                '90_days': ['Collect additional outcomes data for executive benchmarking.']
            }
        }

    ranked = sorted(
        eligible,
        key=lambda x: (x.get('composite_score', 0), x.get('success_rate', 0), x.get('total', 0)),
        reverse=True
    )
    watch = sorted(eligible, key=lambda x: (x.get('composite_score', 0), -x.get('backlog_rate', 0)))

    avg_success = sum(r['success_rate'] for r in eligible) / len(eligible)
    avg_backlog = sum(r['backlog_rate'] for r in eligible) / len(eligible)
    avg_quality = sum(r['composite_score'] for r in eligible) / len(eligible)
    coverage = (len(eligible) / max(1, len(rows))) * 100.0

    top_states = ranked[:5]
    watchlist = watch[:5]

    summary = (
        f"Executive snapshot for {issue_type or 'all issue types'}: "
        f"{len(eligible)} states analyzed, {avg_success:.1f}% average success, "
        f"{avg_backlog:.1f}% average backlog, and {avg_quality:.1f} average quality score."
    )

    return {
        'kpis': {
            'states_analyzed': len(eligible),
            'avg_success': round(avg_success, 1),
            'avg_backlog': round(avg_backlog, 1),
            'avg_quality': round(avg_quality, 1),
            'coverage': round(coverage, 1)
        },
        'top_states': top_states,
        'watchlist': watchlist,
        'summary': summary,
        'actions_30_60_90': {
            '30_days': [
                'Stand up weekly quality review with top and watchlist states.',
                'Target open backlog reduction in high-volume states by 10%.',
                'Publish issue-type playbooks from top performers.'
            ],
            '60_days': [
                'Standardize triage criteria and cancellation controls.',
                'Adopt cross-state KPI scorecards with confidence thresholds.',
                'Track issue aging and improve time-to-close in priority categories.'
            ],
            '90_days': [
                'Launch peer mentoring between top and watchlist states.',
                'Set issue-type specific success targets and accountability owners.',
                'Institutionalize quarterly executive quality brief reporting.'
            ]
        }
    }

def generate_ai_insights(data, issue_type):
    """Generate AI recommendations based on data"""
    eligible = [d for d in data if (d.get('total') or 0) > 0]
    if not eligible:
        return [{
            'type': 'strategic_insight',
            'title': 'Insufficient Data For Reliable Analysis',
            'description': 'No states met the current filter and minimum sample criteria.',
            'recommendation': 'Reduce strict filters or lower the minimum sample threshold to compare more states.'
        }]
 
    insights = []

    ranked = sorted(
        eligible,
        key=lambda x: (x.get('composite_score', 0), x.get('success_rate', 0), x.get('total', 0)),
        reverse=True
    )
    best = ranked[0]
    worst = ranked[-1]

    avg_success = sum(d.get('success_rate', 0) for d in eligible) / len(eligible)
    avg_backlog = sum(d.get('backlog_rate', 0) for d in eligible) / len(eligible)

    insights.append({
        'type': 'strategic_insight',
        'title': f'Dataset Health ({issue_type or "all issue types"})',
        'description': f'Across {len(eligible)} states with data, average success is {avg_success:.1f}% and average backlog is {avg_backlog:.1f}%.',
        'recommendation': 'Use backlog reduction and cancellation prevention as primary levers for system-wide improvement.'
    })

    if best:
        insights.append({
            'type': 'best_performer',
            'title': f'Top Performer: {best["state"]}',
            'description': f'{best["state"]} leads with a composite score of {best["composite_score"]:.1f}, success {best["success_rate"]:.1f}%, confidence {best["confidence"]:.1f}%.',
            'recommendation': f'Capture {best["state"]} playbooks by issue type and reuse them in lower-performing states.'
        })

    if worst:
        insights.append({
            'type': 'improvement_opportunity',
            'title': f'Growth Opportunity: {worst["state"]}',
            'description': f'{worst["state"]} is trailing with score {worst["composite_score"]:.1f}; backlog {worst["backlog_rate"]:.1f}% and cancel rate {worst["cancel_rate"]:.1f}% are the main drag factors.',
            'recommendation': 'Prioritize issue triage, early risk checks, and weekly closure targets to improve throughput.'
        })

    if best and worst:
        score_gap = best.get('composite_score', 0) - worst.get('composite_score', 0)
        if score_gap > 15:
            insights.append({
                'type': 'strategic_insight',
                'title': 'High Performance Variance',
                'description': f'The top-to-bottom composite gap is {score_gap:.1f} points, indicating uneven execution quality across states.',
                'recommendation': 'Launch cross-state quality reviews and standard operating playbooks to normalize outcomes.'
            })

    low_conf = [d for d in eligible if (d.get('confidence') or 0) < 50]
    if low_conf:
        insights.append({
            'type': 'strategic_insight',
            'title': 'Reliability Warning',
            'description': f'{len(low_conf)} states have low confidence due to limited sample sizes.',
            'recommendation': 'Treat those rankings as directional. Add more issues or widen filter scope for stronger reliability.'
        })
    
    return insights

@app.route('/api/ai-chat', methods=['POST'])
def ai_chat():
    """CMS-aware NLP Q&A over Medicaid claim quality data"""
    payload = request.get_json(silent=True) or {}
    question = (payload.get('question') or '').strip()
    if not question:
        return jsonify({'answer': 'Please ask a question.', 'details': []})

    q = question.lower()
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id, name FROM states ORDER BY name')
    state_rows = {r[0]: r[1] for r in cursor.fetchall()}
    state_names = list(state_rows.values())

    # ── CMS type aliases ──────────────────────────────────────────────────────
    CMS_ALIASES = {
        'duplicate':     'duplicate_claims',
        'dup':           'duplicate_claims',
        'duplicate claim': 'duplicate_claims',
        'duplicate claims': 'duplicate_claims',
        'diagnosis':     'invalid_diagnosis_code',
        'icd':           'invalid_diagnosis_code',
        'invalid diagnosis': 'invalid_diagnosis_code',
        'debit':         'debit_credit_mismatch',
        'credit':        'debit_credit_mismatch',
        'mismatch':      'debit_credit_mismatch',
        'null':          'null_recipient_values',
        'recipient':     'null_recipient_values',
        'procedure':     'improper_procedure_code',
        'hcpcs':         'improper_procedure_code',
        'referential':   'referential_integrity',
        'integrity':     'referential_integrity',
        'npi':           'referential_integrity',
        'payment':       'payment_amount_exceeded',
        'exceeded':      'payment_amount_exceeded',
        'overpayment':   'payment_amount_exceeded',
        'birth':         'birth_date_error',
        'birth date':    'birth_date_error',
        'discharge':     'discharge_date_error',
        'discharge date': 'discharge_date_error',
    }
    CMS_LABELS = {
        'duplicate_claims':        'Duplicate Claims',
        'invalid_diagnosis_code':  'Invalid Diagnosis Code',
        'debit_credit_mismatch':   'Debit/Credit Mismatch',
        'null_recipient_values':   'Null Recipient Values',
        'improper_procedure_code': 'Improper Procedure Code',
        'referential_integrity':   'Referential Integrity',
        'payment_amount_exceeded': 'Payment Amount Exceeded',
        'birth_date_error':        'Birth Date Error',
        'discharge_date_error':    'Discharge Date Error',
    }

    # Match issue type from query
    matched_type = ''
    for alias, canonical in CMS_ALIASES.items():
        if alias in q:
            matched_type = canonical
            break
    if not matched_type:
        for canonical in CMS_LABELS:
            if canonical.replace('_', ' ') in q or canonical in q:
                matched_type = canonical
                break

    # Match state from query
    matched_state = next(
        (s for s in sorted(state_names, key=len, reverse=True) if s.lower() in q),
        None)

    # Match quarter from query
    matched_quarter = None
    for qtr in ['Q1 2026', 'Q4 2025', 'Q3 2025', 'Q2 2025']:
        if qtr.lower() in q:
            matched_quarter = qtr
            break

    type_label = CMS_LABELS.get(matched_type, matched_type.replace('_', ' ').title()) if matched_type else 'all issue types'

    # ── Helper: per-state CMS metrics from DB ────────────────────────────────
    def cms_state_metrics(issue_type_filter='', state_id_filter=None):
        sql_type = issue_type_filter or ''
        params = [sql_type, sql_type]
        where = f'AND s.id = {state_id_filter}' if state_id_filter else ''
        cursor.execute(f'''
            SELECT s.id, s.name as state,
                COUNT(i.id) as total,
                SUM(CASE WHEN i.status = "done"      THEN 1 ELSE 0 END) as resolved,
                SUM(CASE WHEN i.status = "open"      THEN 1 ELSE 0 END) as open_cnt,
                SUM(CASE WHEN i.status = "cancelled" THEN 1 ELSE 0 END) as cancelled,
                AVG(CASE WHEN i.issue_type = "duplicate_claims"
                         THEN i.metric_value END) as avg_dup_rate,
                MAX(CASE WHEN i.title LIKE "%Q1 2026%" AND i.issue_type = "duplicate_claims"
                         THEN i.metric_value END) as current_dup_rate,
                SUM(CASE WHEN i.issue_type != "duplicate_claims"
                         THEN i.metric_value ELSE 0 END) as total_case_volume
            FROM states s
            LEFT JOIN issues i ON s.id = i.state_id
                AND (? = "" OR i.issue_type = ?)
            {where}
            GROUP BY s.id, s.name
        ''', params)
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            total = d['total'] or 0
            resolved = d['resolved'] or 0
            d['resolution_rate'] = round(resolved / total * 100, 1) if total else 0
            d['backlog_pct'] = round((d['open_cnt'] or 0) / total * 100, 1) if total else 0
            results.append(d)
        return results

    # ── INTENT: state-specific question ──────────────────────────────────────
    if matched_state:
        cursor.execute('SELECT id FROM states WHERE name = ?', (matched_state,))
        sid_row = cursor.fetchone()
        if not sid_row:
            db.close()
            return jsonify({'answer': f'No data found for {matched_state}.', 'details': []})
        sid = sid_row['id']
        state_idx = state_names.index(matched_state)
        dup_rate = DUP_CLAIM_RATES[state_idx] if state_idx < len(DUP_CLAIM_RATES) else 0

        # Per-type breakdown for this state
        cursor.execute('''
            SELECT issue_type,
                   COUNT(*) as total,
                   SUM(CASE WHEN status = "open"      THEN 1 ELSE 0 END) as open_cnt,
                   SUM(CASE WHEN status = "done"      THEN 1 ELSE 0 END) as resolved,
                   SUM(CASE WHEN status = "cancelled" THEN 1 ELSE 0 END) as cancelled,
                   MAX(CASE WHEN title LIKE "%Q1 2026%" THEN metric_value END) as q1_metric
            FROM issues WHERE state_id = ?
            GROUP BY issue_type
        ''', (sid,))
        type_rows = {r['issue_type']: dict(r) for r in cursor.fetchall()}

        total_issues = sum(v['total'] for v in type_rows.values())
        total_open   = sum(v['open_cnt'] for v in type_rows.values())
        total_done   = sum(v['resolved'] for v in type_rows.values())

        # Nationwide dup rank
        cursor.execute('''
            SELECT s.name, MAX(CASE WHEN i.title LIKE "%Q1 2026%"
                                    AND i.issue_type = "duplicate_claims"
                               THEN i.metric_value END) as dr
            FROM states s JOIN issues i ON i.state_id = s.id
            WHERE i.issue_type = "duplicate_claims"
            GROUP BY s.id HAVING dr IS NOT NULL ORDER BY dr ASC
        ''')
        dup_ranked = [r['name'] for r in cursor.fetchall()]
        dup_rank = dup_ranked.index(matched_state) + 1 if matched_state in dup_ranked else None
        dup_row  = type_rows.get('duplicate_claims', {})
        dup_q1   = dup_row.get('q1_metric') or dup_rate

        if matched_type and matched_type != 'duplicate_claims':
            tr = type_rows.get(matched_type, {})
            q1m = tr.get('q1_metric')
            answer = (
                f'{matched_state} — {type_label}: '
                f'{tr.get("total", 0)} total issues, '
                f'{tr.get("open_cnt", 0)} open, '
                f'{tr.get("resolved", 0)} resolved.'
            )
            details = []
            if q1m is not None:
                details.append(f'Q1 2026 case volume: {int(q1m):,}')
            details += [
                f'Resolution rate: {round(tr["resolved"]/tr["total"]*100,1) if tr.get("total") else 0}%',
                f'Duplicate claim rate (overall): {dup_q1}%',
            ]
            if dup_rank:
                details.append(f'Nationwide dup. rank: #{dup_rank} of {len(dup_ranked)} (lower = better)')
        else:
            answer = (
                f'{matched_state} CMS Quality Snapshot: '
                f'{total_issues} total issues across all claim types — '
                f'{total_done} resolved, {total_open} still open. '
                f'Duplicate claim rate: {dup_q1}%.'
            )
            details = []
            if dup_rank:
                details.append(f'Nationwide dup. rank: #{dup_rank} of {len(dup_ranked)} (1 = lowest rate = best)')
            # Top 3 open issue types
            open_types = sorted(
                [(t, v['open_cnt']) for t, v in type_rows.items() if v.get('open_cnt', 0) > 0],
                key=lambda x: x[1], reverse=True)[:3]
            for t, cnt in open_types:
                details.append(f'Open — {CMS_LABELS.get(t, t)}: {cnt} issues')
            # Any type with a Q1 2026 metric
            for t, v in type_rows.items():
                if v.get('q1_metric') and t != 'duplicate_claims':
                    details.append(f'Q1 2026 case volume ({CMS_LABELS.get(t, t)}): {int(v["q1_metric"]):,}')
                    break

        db.close()
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: duplicate claims / rates ─────────────────────────────────────
    if matched_type == 'duplicate_claims' or re.search(
            r'\b(dup|duplicate|claim rate)\b', q):
        cursor.execute('''
            SELECT s.name,
                   MAX(CASE WHEN i.title LIKE "%Q1 2026%"
                            AND i.issue_type = "duplicate_claims"
                       THEN i.metric_value END) as rate
            FROM states s JOIN issues i ON i.state_id = s.id
            WHERE i.issue_type = "duplicate_claims"
            GROUP BY s.id HAVING rate IS NOT NULL ORDER BY rate ASC
        ''')
        dup_rows = cursor.fetchall()
        db.close()
        if not dup_rows:
            return jsonify({'answer': 'No duplicate claims data found.', 'details': []})

        rates = [r['rate'] for r in dup_rows]
        avg_rate = round(sum(rates) / len(rates), 2)

        if re.search(r'\b(best|lowest|least|top)\b', q):
            answer = f'States with the lowest duplicate claim rates (Q1 2026):'
            details = [f"#{i+1} {r['name']}: {r['rate']}%" for i, r in enumerate(dup_rows[:7])]
        elif re.search(r'\b(worst|highest|most|bottom)\b', q):
            worst = list(reversed(dup_rows))
            answer = f'States with the highest duplicate claim rates (Q1 2026):'
            details = [f"#{i+1} {r['name']}: {r['rate']}%" for i, r in enumerate(worst[:7])]
        else:
            best = dup_rows[0]
            worst = dup_rows[-1]
            answer = (
                f'Duplicate Claims — Q1 2026 nationwide: '
                f'avg rate {avg_rate}%, '
                f'best {best["name"]} {best["rate"]}%, '
                f'worst {worst["name"]} {worst["rate"]}%.'
            )
            details = [f"{r['name']}: {r['rate']}%" for r in dup_rows[:8]]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: specific non-dup issue type ──────────────────────────────────
    if matched_type:
        cursor.execute('''
            SELECT s.name,
                   MAX(CASE WHEN i.title LIKE "%Q1 2026%" THEN i.metric_value END) as q1_vol,
                   SUM(CASE WHEN i.status = "open" THEN 1 ELSE 0 END) as open_cnt,
                   COUNT(*) as total
            FROM states s JOIN issues i ON i.state_id = s.id
            WHERE i.issue_type = ?
            GROUP BY s.id HAVING q1_vol IS NOT NULL
            ORDER BY q1_vol ASC
        ''', (matched_type,))
        type_ranked = cursor.fetchall()
        db.close()

        if not type_ranked:
            return jsonify({'answer': f'No Q1 2026 data found for {type_label}.', 'details': []})

        vols = [r['q1_vol'] for r in type_ranked]
        avg_vol = round(sum(vols) / len(vols), 0)

        if re.search(r'\b(best|lowest|least|fewest)\b', q):
            answer = f'{type_label} — states with fewest Q1 2026 cases (best):'
            details = [f"#{i+1} {r['name']}: {int(r['q1_vol']):,} cases, {r['open_cnt']} open" for i, r in enumerate(type_ranked[:7])]
        elif re.search(r'\b(worst|highest|most|critical)\b', q):
            worst_list = list(reversed(type_ranked))
            answer = f'{type_label} — states with most Q1 2026 cases (worst):'
            details = [f"#{i+1} {r['name']}: {int(r['q1_vol']):,} cases, {r['open_cnt']} open" for i, r in enumerate(worst_list[:7])]
        elif re.search(r'\b(open|backlog|unresolved)\b', q):
            most_open = sorted(type_ranked, key=lambda x: x['open_cnt'], reverse=True)
            answer = f'{type_label} — states with most open issues:'
            details = [f"{r['name']}: {r['open_cnt']} open, Q1 vol {int(r['q1_vol']):,}" for r in most_open[:7]]
        else:
            best = type_ranked[0]
            worst_r = type_ranked[-1]
            answer = (
                f'{type_label} — Q1 2026 snapshot across {len(type_ranked)} states: '
                f'avg {int(avg_vol):,} cases. '
                f'Best: {best["name"]} ({int(best["q1_vol"]):,}). '
                f'Most cases: {worst_r["name"]} ({int(worst_r["q1_vol"]):,}).'
            )
            details = [f"{r['name']}: {int(r['q1_vol']):,} cases" for r in type_ranked[:8]]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: open / backlog ────────────────────────────────────────────────
    if re.search(r'\b(open|backlog|unresolved|pending)\b', q):
        cursor.execute('''
            SELECT s.name,
                   SUM(CASE WHEN i.status = "open" THEN 1 ELSE 0 END) as open_cnt,
                   COUNT(*) as total
            FROM states s JOIN issues i ON i.state_id = s.id
            GROUP BY s.id ORDER BY open_cnt DESC
        ''')
        open_rows = cursor.fetchall()
        db.close()
        top_open = [r for r in open_rows if r['open_cnt'] > 0][:8]
        answer = 'States with the most open CMS quality issues:'
        details = [
            f"{r['name']}: {r['open_cnt']} open of {r['total']} total "
            f"({round(r['open_cnt']/r['total']*100,1) if r['total'] else 0}% backlog)"
            for r in top_open]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: resolved / completed ─────────────────────────────────────────
    if re.search(r'\b(resolved|done|completed|closed|finished)\b', q):
        cursor.execute('''
            SELECT s.name,
                   SUM(CASE WHEN i.status = "done" THEN 1 ELSE 0 END) as done_cnt,
                   COUNT(*) as total
            FROM states s JOIN issues i ON i.state_id = s.id
            GROUP BY s.id HAVING total > 0 ORDER BY done_cnt DESC
        ''')
        done_rows = cursor.fetchall()
        db.close()
        answer = 'States with the most resolved CMS quality issues:'
        details = [
            f"{r['name']}: {r['done_cnt']} resolved "
            f"({round(r['done_cnt']/r['total']*100,1) if r['total'] else 0}% resolution rate)"
            for r in done_rows[:8]]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: compare / rank all types ─────────────────────────────────────
    if re.search(r'\b(compare|rank|ranking|leaderboard|scorecard)\b', q):
        cursor.execute('''
            SELECT s.name,
                   COUNT(*) as total,
                   SUM(CASE WHEN i.status = "done" THEN 1 ELSE 0 END) as done_cnt,
                   SUM(CASE WHEN i.status = "open" THEN 1 ELSE 0 END) as open_cnt,
                   MAX(CASE WHEN i.title LIKE "%Q1 2026%" AND i.issue_type = "duplicate_claims"
                       THEN i.metric_value END) as dup_rate
            FROM states s JOIN issues i ON i.state_id = s.id
            GROUP BY s.id HAVING total > 0
            ORDER BY dup_rate ASC, done_cnt DESC
        ''')
        cmp_rows = cursor.fetchall()
        db.close()
        answer = (
            f'CMS quality comparison across all 50 states — '
            f'ranked by duplicate claim rate (Q1 2026), then by resolved issues.'
        )
        details = [
            f"{r['name']}: dup rate {r['dup_rate'] or '–'}%, "
            f"{r['done_cnt']} resolved / {r['total']} total"
            for r in cmp_rows[:10]]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: best / top states overall ────────────────────────────────────
    if re.search(r'\b(best|top|leader|excellent|performing)\b', q):
        cursor.execute('''
            SELECT s.name,
                   MAX(CASE WHEN i.title LIKE "%Q1 2026%" AND i.issue_type = "duplicate_claims"
                       THEN i.metric_value END) as dup_rate,
                   SUM(CASE WHEN i.status = "open" THEN 1 ELSE 0 END) as open_cnt,
                   COUNT(*) as total
            FROM states s JOIN issues i ON i.state_id = s.id
            GROUP BY s.id HAVING dup_rate IS NOT NULL
            ORDER BY dup_rate ASC
        ''')
        best_rows = cursor.fetchall()
        db.close()
        answer = 'Top-performing states by lowest duplicate claim rate (Q1 2026):'
        details = [
            f"#{i+1} {r['name']}: {r['dup_rate']}% dup rate, {r['open_cnt']} open issues"
            for i, r in enumerate(best_rows[:7])]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: worst / critical states ──────────────────────────────────────
    if re.search(r'\b(worst|bottom|critical|lagging|failing|poor)\b', q):
        cursor.execute('''
            SELECT s.name,
                   MAX(CASE WHEN i.title LIKE "%Q1 2026%" AND i.issue_type = "duplicate_claims"
                       THEN i.metric_value END) as dup_rate,
                   SUM(CASE WHEN i.status = "open" THEN 1 ELSE 0 END) as open_cnt,
                   COUNT(*) as total
            FROM states s JOIN issues i ON i.state_id = s.id
            GROUP BY s.id HAVING dup_rate IS NOT NULL
            ORDER BY dup_rate DESC
        ''')
        worst_rows = cursor.fetchall()
        db.close()
        answer = 'States needing the most CMS quality improvement (highest dup. claim rates):'
        details = [
            f"#{i+1} {r['name']}: {r['dup_rate']}% dup rate, {r['open_cnt']} open issues"
            for i, r in enumerate(worst_rows[:7])]
        return jsonify({'answer': answer, 'details': details})

    # ── INTENT: quarter-specific ──────────────────────────────────────────────
    if matched_quarter:
        cursor.execute('''
            SELECT s.name, i.issue_type,
                   COUNT(*) as cnt,
                   AVG(i.metric_value) as avg_metric
            FROM issues i JOIN states s ON s.id = i.state_id
            WHERE i.title LIKE ?
            GROUP BY s.id, i.issue_type
            ORDER BY avg_metric DESC
        ''', (f'%{matched_quarter}%',))
        q_rows = cursor.fetchall()
        db.close()
        if not q_rows:
            return jsonify({'answer': f'No data found for {matched_quarter}.', 'details': []})
        answer = f'{matched_quarter} reporting period — top claim quality issues by volume:'
        seen = {}
        details = []
        for r in q_rows:
            key = r['issue_type']
            if key not in seen and r['avg_metric']:
                seen[key] = True
                details.append(
                    f"{CMS_LABELS.get(key, key)}: avg {int(r['avg_metric']):,} cases across {r['cnt']} state records")
            if len(details) >= 7:
                break
        return jsonify({'answer': answer, 'details': details})

    # ── DEFAULT: overall CMS snapshot ────────────────────────────────────────
    cursor.execute('''
        SELECT SUM(CASE WHEN status = "open"      THEN 1 ELSE 0 END) as open_cnt,
               SUM(CASE WHEN status = "done"      THEN 1 ELSE 0 END) as done_cnt,
               SUM(CASE WHEN status = "cancelled" THEN 1 ELSE 0 END) as canc_cnt,
               COUNT(*) as total
        FROM issues
    ''')
    totals = dict(cursor.fetchone())
    cursor.execute('''
        SELECT AVG(CASE WHEN title LIKE "%Q1 2026%" AND issue_type = "duplicate_claims"
                   THEN metric_value END) as avg_dup
        FROM issues
    ''')
    avg_dup = cursor.fetchone()['avg_dup']
    db.close()

    total = totals['total'] or 1
    answer = (
        f'CMS Quality Overview — {total:,} total issues across all 50 states: '
        f'{totals["done_cnt"]:,} resolved ({round(totals["done_cnt"]/total*100,1)}%), '
        f'{totals["open_cnt"]:,} open ({round(totals["open_cnt"]/total*100,1)}%). '
        f'National avg duplicate claim rate (Q1 2026): {round(avg_dup, 2) if avg_dup else "–"}%.'
    )
    details = [
        'Try asking: "duplicate claim rate by state"',
        'Try asking: "worst states for invalid diagnosis code"',
        'Try asking: "open issues in Texas"',
        'Try asking: "compare Q1 2026"',
        'Try asking: "best states for payment amount exceeded"',
    ]
    return jsonify({'answer': answer, 'details': details})


@app.route('/executive-brief')
def executive_brief_page():
    """Executive-ready briefing page"""
    issue_type = (request.args.get('issue_type') or '').strip().lower()
    min_total = request.args.get('min_total', type=int)
    if min_total is None:
        min_total = 3

    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT DISTINCT issue_type FROM issues ORDER BY issue_type')
    issue_types = [row[0] for row in cursor.fetchall() if row[0]]
    db.close()

    brief = build_executive_brief(issue_type=issue_type, min_total=min_total)
    return render_template(
        'executive_brief.html',
        issue_types=issue_types,
        selected_type=issue_type,
        min_total=min_total,
        brief=brief
    )


@app.route('/api/executive-brief')
def executive_brief_api():
    """API for dynamic executive brief filtering"""
    issue_type = (request.args.get('issue_type') or '').strip().lower()
    min_total = request.args.get('min_total', type=int)
    if min_total is None:
        min_total = 3

    brief = build_executive_brief(issue_type=issue_type, min_total=min_total)
    return jsonify(brief)

@app.route('/heatmap')
def heatmap():
    """US heatmap view with drill-down by state"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id, name FROM tags ORDER BY name')
    tags = [dict(row) for row in cursor.fetchall()]

    cursor.execute('SELECT DISTINCT issue_type FROM issues ORDER BY issue_type')
    issue_types = [row[0] for row in cursor.fetchall() if row[0]]

    db.close()

    return render_template('heatmap.html', tags=tags, issue_types=issue_types)


def get_heatmap_rows(status='', issue_type='', tag_id=0):
    """Return per-state aggregates for heatmap with applied filters"""
    db = get_db()
    cursor = db.cursor()

    tag_id = int(tag_id or 0)
    params = [
        issue_type, issue_type,
        status, status,
        tag_id, tag_id
    ]

    cursor.execute('''
        SELECT s.id,
               s.name,
               COUNT(fi.id) as total,
               SUM(CASE WHEN fi.status = 'done' THEN 1 ELSE 0 END) as successful,
               SUM(CASE WHEN fi.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
               SUM(CASE WHEN fi.status = 'open' THEN 1 ELSE 0 END) as open
        FROM states s
        LEFT JOIN (
            SELECT i.*
            FROM issues i
            WHERE (? = '' OR LOWER(i.issue_type) = ?)
              AND (? = '' OR i.status = ?)
              AND (
                    ? = 0
                    OR EXISTS (
                        SELECT 1
                        FROM issue_tags it
                        WHERE it.issue_id = i.id
                          AND it.tag_id = ?
                    )
                  )
        ) fi ON fi.state_id = s.id
        GROUP BY s.id, s.name
        ORDER BY s.name
    ''', params)

    rows = []
    for row in cursor.fetchall():
        item = dict(row)
        total = item['total'] or 0
        done = item['successful'] or 0
        cancelled = item['cancelled'] or 0
        open_count = item['open'] or 0

        success_rate = (done / total * 100.0) if total > 0 else 0.0
        cancel_rate = (cancelled / total * 100.0) if total > 0 else 0.0
        backlog_rate = (open_count / total * 100.0) if total > 0 else 0.0
        quality_score = (
            (0.55 * success_rate) +
            (0.25 * (100.0 - cancel_rate)) +
            (0.20 * (100.0 - backlog_rate))
        )

        item.update({
            'state_code': STATE_ABBR.get(item['name'], ''),
            'success_rate': round(success_rate, 1),
            'cancel_rate': round(cancel_rate, 1),
            'backlog_rate': round(backlog_rate, 1),
            'quality_score': round(quality_score, 1)
        })
        rows.append(item)

    db.close()
    return rows


@app.route('/api/heatmap-data')
def heatmap_data():
    """Heatmap dataset endpoint"""
    status = (request.args.get('status') or '').strip().lower()
    issue_type = (request.args.get('issue_type') or '').strip().lower()
    tag_id = request.args.get('tag_id', type=int) or 0
    metric = (request.args.get('metric') or 'quality_score').strip().lower()

    rows = get_heatmap_rows(status=status, issue_type=issue_type, tag_id=tag_id)

    valid_metrics = {
        'quality_score', 'success_rate', 'total', 'successful', 'open', 'cancelled', 'backlog_rate', 'cancel_rate'
    }
    if metric not in valid_metrics:
        metric = 'quality_score'

    for row in rows:
        row['metric_value'] = row.get(metric, 0)

    return jsonify({'metric': metric, 'rows': rows})


@app.route('/api/heatmap-state/<int:state_id>')
def heatmap_state_detail(state_id):
    """State drill-down details with filtered issues"""
    status = (request.args.get('status') or '').strip().lower()
    issue_type = (request.args.get('issue_type') or '').strip().lower()
    tag_id = request.args.get('tag_id', type=int) or 0

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id, name FROM states WHERE id = ?', (state_id,))
    state = cursor.fetchone()
    if not state:
        db.close()
        return jsonify({'error': 'State not found'}), 404

    params = [state_id, issue_type, issue_type, status, status, tag_id, tag_id]
    cursor.execute('''
        SELECT i.id,
               i.title,
               i.description,
               i.status,
               i.priority,
               i.issue_type,
               i.created_at,
               GROUP_CONCAT(DISTINCT t.name) as tags
        FROM issues i
        LEFT JOIN issue_tags it ON i.id = it.issue_id
        LEFT JOIN tags t ON it.tag_id = t.id
        WHERE i.state_id = ?
          AND (? = '' OR LOWER(i.issue_type) = ?)
          AND (? = '' OR i.status = ?)
          AND (
                ? = 0
                OR EXISTS (
                    SELECT 1 FROM issue_tags it2
                    WHERE it2.issue_id = i.id
                      AND it2.tag_id = ?
                )
              )
        GROUP BY i.id
        ORDER BY i.updated_at DESC, i.created_at DESC
        LIMIT 300
    ''', params)
    issues = [dict(row) for row in cursor.fetchall()]

    total = len(issues)
    successful = sum(1 for i in issues if i['status'] == 'done')
    open_count = sum(1 for i in issues if i['status'] == 'open')
    cancelled = sum(1 for i in issues if i['status'] == 'cancelled')
    success_rate = (successful / total * 100.0) if total > 0 else 0.0

    db.close()

    return jsonify({
        'state': {'id': state['id'], 'name': state['name'], 'code': STATE_ABBR.get(state['name'], '')},
        'summary': {
            'total': total,
            'successful': successful,
            'open': open_count,
            'cancelled': cancelled,
            'success_rate': round(success_rate, 1)
        },
        'issues': issues
    })

@app.route('/api/search')
def search():
    """Global search across states and issues"""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'states': [], 'issues': []})

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        'SELECT id, name FROM states WHERE name LIKE ? ORDER BY name LIMIT 8',
        (f'%{q}%',)
    )
    states = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT i.id, i.title, i.status, i.issue_type, i.priority,
               s.name as state_name, s.id as state_id
        FROM issues i
        JOIN states s ON i.state_id = s.id
        WHERE i.title LIKE ? OR i.description LIKE ?
        ORDER BY i.updated_at DESC
        LIMIT 12
    ''', (f'%{q}%', f'%{q}%'))
    issues = [dict(row) for row in cursor.fetchall()]

    db.close()
    return jsonify({'states': states, 'issues': issues})


@app.route('/api/export/issues.csv')
def export_issues_csv():
    """Export filtered issues as a downloadable CSV"""
    from io import StringIO
    import csv as csv_lib

    status_filter = (request.args.get('status') or '').strip().lower()
    type_filter = (request.args.get('issue_type') or '').strip().lower()
    state_filter = (request.args.get('state') or '').strip()

    db = get_db()
    cursor = db.cursor()

    query = '''
        SELECT s.name as state, i.title, i.description, i.status, i.priority,
               i.issue_type, i.created_at, i.updated_at,
               GROUP_CONCAT(DISTINCT t.name) as tags
        FROM issues i
        JOIN states s ON i.state_id = s.id
        LEFT JOIN issue_tags it ON i.id = it.issue_id
        LEFT JOIN tags t ON it.tag_id = t.id
        WHERE 1=1
    '''
    params = []
    if status_filter:
        query += ' AND i.status = ?'
        params.append(status_filter)
    if type_filter:
        query += ' AND LOWER(i.issue_type) = ?'
        params.append(type_filter)
    if state_filter:
        query += ' AND s.name LIKE ?'
        params.append(f'%{state_filter}%')

    query += ' GROUP BY i.id ORDER BY s.name, i.updated_at DESC'
    cursor.execute(query, params)
    rows = cursor.fetchall()
    db.close()

    output = StringIO()
    writer = csv_lib.writer(output)
    writer.writerow(['State', 'Title', 'Description', 'Status', 'Priority',
                     'Issue Type', 'Created', 'Updated', 'Tags'])
    for row in rows:
        writer.writerow([
            row['state'], row['title'], row['description'] or '', row['status'],
            row['priority'], row['issue_type'], row['created_at'], row['updated_at'],
            row['tags'] or ''
        ])

    from flask import make_response
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename=state_issues_export.csv'
    return resp


@app.route('/api/state-executive-summary/<int:state_id>')
def state_executive_summary(state_id):
    """Return CMS quality executive summary for a single state"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM states WHERE id = ?', (state_id,))
    state_row = cursor.fetchone()
    if not state_row:
        db.close()
        return jsonify({'error': 'State not found'}), 404

    # Metrics by issue type for this state
    cursor.execute('''
        SELECT issue_type,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count,
               MAX(CASE WHEN title LIKE '%Q1 2026%' THEN metric_value ELSE NULL END) as current_metric
        FROM issues
        WHERE state_id = ?
        GROUP BY issue_type
    ''', (state_id,))
    type_data = {row['issue_type']: dict(row) for row in cursor.fetchall()}

    # Nationwide dup claim rates for ranking (lower = better)
    cursor.execute('''
        SELECT s.id as state_id,
               MAX(CASE WHEN i.title LIKE '%Q1 2026%' AND i.issue_type = 'duplicate_claims'
                        THEN i.metric_value END) as dup_rate
        FROM states s
        JOIN issues i ON i.state_id = s.id
        WHERE i.issue_type = 'duplicate_claims'
        GROUP BY s.id
        HAVING dup_rate IS NOT NULL
        ORDER BY dup_rate ASC
    ''')
    all_dup_rows = cursor.fetchall()
    national_avg_dup = sum(r['dup_rate'] for r in all_dup_rows) / max(len(all_dup_rows), 1)
    state_dup_rate = (type_data.get('duplicate_claims') or {}).get('current_metric') or 0
    dup_rank = next((i + 1 for i, r in enumerate(all_dup_rows) if r['state_id'] == state_id), None)

    # Per-issue-type nationwide ranks
    issue_type_rankings = {}
    for issue_type in CMS_ISSUE_TYPES:
        if issue_type == 'duplicate_claims':
            issue_type_rankings[issue_type] = dup_rank
            continue
        cursor.execute('''
            SELECT s.id,
                   MAX(CASE WHEN i.title LIKE '%Q1 2026%' THEN i.metric_value END) as cur
            FROM states s
            JOIN issues i ON i.state_id = s.id
            WHERE i.issue_type = ?
            GROUP BY s.id
            HAVING cur IS NOT NULL
            ORDER BY cur ASC
        ''', (issue_type,))
        ranked = cursor.fetchall()
        issue_type_rankings[issue_type] = next((i + 1 for i, r in enumerate(ranked) if r['id'] == state_id), None)

    # Quality grade
    high_open = sum(1 for t, d in type_data.items() if (d.get('open_count') or 0) > 0 and t != 'duplicate_claims')
    if state_dup_rate < 1.5 and high_open <= 2:
        grade = 'A'
    elif state_dup_rate < 3.0 and high_open <= 5:
        grade = 'B'
    elif state_dup_rate < 5.0:
        grade = 'C'
    elif state_dup_rate < 6.5:
        grade = 'D'
    else:
        grade = 'F'

    db.close()
    return jsonify({
        'state': dict(state_row),
        'type_breakdown': type_data,
        'duplicate_claims': {
            'rate': round(state_dup_rate, 2),
            'national_avg': round(national_avg_dup, 2),
            'rank': dup_rank,
            'total_states': len(all_dup_rows),
            'vs_national': round(state_dup_rate - national_avg_dup, 2)
        },
        'issue_type_rankings': issue_type_rankings,
        'quality_grade': grade
    })


@app.route('/api/nationwide-rankings')
def nationwide_rankings():
    """Return nationwide CMS quality rankings by issue type"""
    db = get_db()
    cursor = db.cursor()

    rankings = {}
    for issue_type in CMS_ISSUE_TYPES:
        cursor.execute('''
            SELECT s.id, s.name,
                   MAX(CASE WHEN i.title LIKE '%Q1 2026%' THEN i.metric_value END) as current_metric,
                   SUM(CASE WHEN i.status = 'open' THEN 1 ELSE 0 END) as open_issues
            FROM states s
            JOIN issues i ON i.state_id = s.id
            WHERE i.issue_type = ?
            GROUP BY s.id
            HAVING current_metric IS NOT NULL
            ORDER BY current_metric ASC
        ''', (issue_type,))
        rows = cursor.fetchall()
        rankings[issue_type] = [
            {'rank': i + 1, 'state_id': r['id'], 'state': r['name'],
             'metric': r['current_metric'], 'open_issues': r['open_issues']}
            for i, r in enumerate(rows)
        ]

    db.close()
    return jsonify({
        'rankings': rankings,
        'duplicate_claims_ranking': rankings.get('duplicate_claims', []),
        'issue_types': CMS_ISSUE_TYPES,
        'issue_type_labels': CMS_ISSUE_TITLES
    })


# Ensure schema/data are initialized for both local run and WSGI (gunicorn/Render)
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
