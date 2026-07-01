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

    # Ensure all states and tags exist
    for state in ALL_STATES:
        cursor.execute('INSERT OR IGNORE INTO states (name) VALUES (?)', (state,))

    tags = ['needs improvement', 'will probably benefit', 'will not benefit', 'urgent', 'completed', 'in progress']
    for tag in tags:
        cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag,))

    db.commit()

    # Seed demo issues only if none exist
    cursor.execute('SELECT COUNT(*) FROM issues')
    has_issues = cursor.fetchone()[0] > 0

    if not has_issues:
        # Add dummy issues
        dummy_issues = [
            ('California', 'Infrastructure improvement program', 'Needs modernization of public roads', 'open', 'high', 'infrastructure'),
            ('California', 'Education funding boost', 'Increase funding for tech programs', 'done', 'medium', 'education'),
            ('California', 'Environmental cleanup', 'Clean up coastal areas', 'cancelled', 'medium', 'environment'),
            ('Texas', 'Water resource management', 'Better irrigation systems', 'open', 'high', 'environment'),
            ('Texas', 'Job training initiatives', 'Tech workforce development', 'open', 'medium', 'workforce'),
            ('Texas', 'Health care expansion', 'Rural clinic establishment', 'done', 'high', 'healthcare'),
            ('Florida', 'Hurricane preparedness', 'Emergency response systems', 'open', 'high', 'emergency'),
            ('Florida', 'Tourism promotion', 'New destination marketing', 'done', 'low', 'commerce'),
            ('Florida', 'Coastal erosion control', 'Beach restoration project', 'open', 'high', 'environment'),
            ('New York', 'Public transit upgrade', 'Modernize subway system', 'open', 'medium', 'infrastructure'),
            ('New York', 'Tech hub development', 'Support startups and innovation', 'done', 'high', 'technology'),
            ('New York', 'Housing affordability', 'Build more affordable units', 'open', 'high', 'housing'),
            ('Pennsylvania', 'Manufacturing support', 'Revitalize industrial areas', 'open', 'medium', 'commerce'),
            ('Pennsylvania', 'Clean energy transition', 'Shift to renewable sources', 'open', 'high', 'environment'),
            ('Pennsylvania', 'Community development', 'Support small businesses', 'done', 'medium', 'commerce'),
            ('Illinois', 'Transportation network', 'Expand rail infrastructure', 'open', 'medium', 'infrastructure'),
            ('Illinois', 'STEM education', 'Improve science programs', 'done', 'high', 'education'),
            ('Illinois', 'Pollution reduction', 'Air quality improvement', 'open', 'medium', 'environment'),
        ]

        tag_mapping = {
            0: [0, 2],  # California issue 1: needs improvement, will not benefit
            1: [1, 4],  # California issue 2: will probably benefit, completed
            2: [2, 5],  # California issue 3: will not benefit, in progress
            3: [0, 1],  # Texas issue 1: needs improvement, will probably benefit
            4: [1, 2],  # Texas issue 2: will probably benefit, will not benefit
            5: [1, 4],  # Texas issue 3: will probably benefit, completed
            6: [0, 3],  # Florida issue 1: needs improvement, urgent
            7: [4, 1],  # Florida issue 2: completed, will probably benefit
            8: [0, 3],  # Florida issue 3: needs improvement, urgent
            9: [0, 1],  # New York issue 1: needs improvement, will probably benefit
            10: [1, 4], # New York issue 2: will probably benefit, completed
            11: [0, 1], # New York issue 3: needs improvement, will probably benefit
            12: [1, 2], # Pennsylvania issue 1: will probably benefit, will not benefit
            13: [1, 3], # Pennsylvania issue 2: will probably benefit, urgent
            14: [4, 1], # Pennsylvania issue 3: completed, will probably benefit
            15: [0, 1], # Illinois issue 1: needs improvement, will probably benefit
            16: [4, 1], # Illinois issue 2: completed, will probably benefit
            17: [0, 1], # Illinois issue 3: needs improvement, will probably benefit
        }

        for idx, (state, title, desc, status, priority, issue_type) in enumerate(dummy_issues):
            cursor.execute('''
                INSERT INTO issues (state_id, title, description, status, priority, issue_type)
                VALUES ((SELECT id FROM states WHERE name = ?), ?, ?, ?, ?, ?)
            ''', (state, title, desc, status, priority, issue_type))

            issue_id = cursor.lastrowid
            for tag_id in tag_mapping.get(idx, []):
                cursor.execute('INSERT INTO issue_tags (issue_id, tag_id) VALUES (?, ?)', (issue_id, tag_id + 1))

    # Ensure every state has at least one issue
    cursor.execute('''
        SELECT s.name
        FROM states s
        LEFT JOIN issues i ON i.state_id = s.id
        GROUP BY s.id, s.name
        HAVING COUNT(i.id) = 0
    ''')

    missing_issue_states = [row[0] for row in cursor.fetchall()]
    for state_name in missing_issue_states:
        cursor.execute('''
            INSERT INTO issues (state_id, title, description, status, priority, issue_type)
            VALUES (
                (SELECT id FROM states WHERE name = ?),
                ?, ?, 'open', 'medium', 'general'
            )
        ''', (
            state_name,
            f'{state_name} Community Improvement Plan',
            f'Baseline issue record for {state_name}. Add custom issues to track local priorities.'
        ))

    # Generate additional diverse issues so the dataset is substantial and realistic
    cursor.execute('SELECT COUNT(*) FROM issues')
    current_issue_count = cursor.fetchone()[0]
    target_issue_count = 520

    if current_issue_count < target_issue_count:
        cursor.execute('SELECT id, name FROM states ORDER BY name')
        state_rows = cursor.fetchall()

        cursor.execute('SELECT id, name FROM tags ORDER BY id')
        tag_rows = cursor.fetchall()
        tag_lookup = {row['name']: row['id'] for row in tag_rows}

        status_cycle = ['open', 'done', 'open', 'open', 'done', 'cancelled', 'open', 'done']
        priority_cycle = ['high', 'medium', 'low', 'medium', 'high', 'medium']

        to_create = target_issue_count - current_issue_count
        for idx in range(to_create):
            state = state_rows[idx % len(state_rows)]
            issue_type = ISSUE_TYPES[(idx + state['id']) % len(ISSUE_TYPES)]
            title_template = ISSUE_TITLE_TEMPLATES[issue_type][idx % 3]
            title = f"{state['name']} {title_template} #{idx + 1}"
            description = (
                f"{state['name']} program update for {issue_type.replace('_', ' ')}. "
                f"Tracks milestones, implementation risk, and outcomes for quality reporting."
            )

            status = status_cycle[idx % len(status_cycle)]
            priority = priority_cycle[(idx + state['id']) % len(priority_cycle)]

            cursor.execute('''
                INSERT INTO issues (state_id, title, description, status, priority, issue_type)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (state['id'], title, description, status, priority, issue_type))

            issue_id = cursor.lastrowid

            # Attach multiple tags to improve downstream analytics
            tag_names = {'in progress'}
            if status == 'done':
                tag_names.add('completed')
                tag_names.add('will probably benefit')
            elif status == 'cancelled':
                tag_names.add('will not benefit')
                if priority == 'high':
                    tag_names.add('urgent')
            else:
                tag_names.add('needs improvement')
                if priority == 'high':
                    tag_names.add('urgent')
                else:
                    tag_names.add('will probably benefit')

            for tag_name in tag_names:
                tag_id = tag_lookup.get(tag_name)
                if tag_id:
                    cursor.execute('INSERT OR IGNORE INTO issue_tags (issue_id, tag_id) VALUES (?, ?)', (issue_id, tag_id))

    # Ensure each state has at least one issue for each issue type (improves filtered AI accuracy)
    cursor.execute('SELECT id, name FROM states ORDER BY name')
    state_rows = cursor.fetchall()
    cursor.execute('SELECT id, name FROM tags ORDER BY id')
    tag_rows = cursor.fetchall()
    tag_lookup = {row['name']: row['id'] for row in tag_rows}

    for state in state_rows:
        for type_idx, issue_type in enumerate(ISSUE_TYPES):
            cursor.execute('''
                SELECT COUNT(*)
                FROM issues
                WHERE state_id = ? AND LOWER(issue_type) = ?
            ''', (state['id'], issue_type))
            existing_count = cursor.fetchone()[0]

            if existing_count == 0:
                selector = (state['id'] + type_idx) % 6
                if selector in (0, 3):
                    status = 'done'
                    tags_to_add = ['completed', 'will probably benefit', 'in progress']
                elif selector == 5:
                    status = 'cancelled'
                    tags_to_add = ['will not benefit', 'in progress']
                else:
                    status = 'open'
                    tags_to_add = ['needs improvement', 'in progress']

                priority = ['low', 'medium', 'high'][(state['id'] + type_idx) % 3]
                title = f"{state['name']} {issue_type.replace('_', ' ').title()} Quality Initiative"
                description = (
                    f"Standardized {issue_type.replace('_', ' ')} quality tracking record for {state['name']} "
                    f"to support consistent cross-state benchmarking."
                )

                cursor.execute('''
                    INSERT INTO issues (state_id, title, description, status, priority, issue_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (state['id'], title, description, status, priority, issue_type))

                issue_id = cursor.lastrowid
                for tag_name in tags_to_add:
                    tag_id = tag_lookup.get(tag_name)
                    if tag_id:
                        cursor.execute('INSERT OR IGNORE INTO issue_tags (issue_id, tag_id) VALUES (?, ?)', (issue_id, tag_id))

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
    """Simple NLP-style Q&A over issue data"""
    payload = request.get_json(silent=True) or {}
    question = (payload.get('question') or '').strip()
    if not question:
        return jsonify({'answer': 'Please ask a question.', 'details': []})

    q = question.lower()
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT name FROM states ORDER BY name')
    state_names = [r[0] for r in cursor.fetchall()]

    cursor.execute('SELECT DISTINCT LOWER(issue_type) FROM issues ORDER BY issue_type')
    issue_types = [r[0] for r in cursor.fetchall() if r[0]]
    db.close()

    matched_state = next((s for s in state_names if s.lower() in q), None)
    matched_type = next((t for t in issue_types if t in q), '')

    rows = get_comparison_rows(issue_type=matched_type)
    eligible = [r for r in rows if (r.get('total') or 0) > 0]
    ranked = sorted(eligible, key=lambda x: x.get('composite_score', 0), reverse=True)

    if matched_state:
        item = next((r for r in rows if r['state'] == matched_state), None)
        if not item:
            return jsonify({'answer': f'I could not find data for {matched_state}.', 'details': []})

        answer = (
            f'{matched_state}: {item["total"]} total issues, {item["successful"]} completed, '
            f'{item["open"]} open, {item["cancelled"]} cancelled. '
            f'Success rate {item["success_rate"]:.1f}%, composite score {item["composite_score"]:.1f}.'
        )
        details = [
            f'Backlog rate: {item["backlog_rate"]:.1f}%',
            f'Cancellation rate: {item["cancel_rate"]:.1f}%',
            f'Data confidence: {item["confidence"]:.1f}%'
        ]
        return jsonify({'answer': answer, 'details': details})

    if re.search(r'\b(best|top|leader)\b', q):
        top = ranked[:5]
        answer = 'Top states by composite quality score:'
        details = [f"{r['state']}: score {r['composite_score']:.1f}, success {r['success_rate']:.1f}%" for r in top]
        return jsonify({'answer': answer, 'details': details})

    if re.search(r'\b(worst|bottom|lagging|lowest)\b', q):
        bottom = sorted(eligible, key=lambda x: x.get('composite_score', 0))[:5]
        answer = 'States needing the most improvement:'
        details = [f"{r['state']}: score {r['composite_score']:.1f}, backlog {r['backlog_rate']:.1f}%, cancel {r['cancel_rate']:.1f}%" for r in bottom]
        return jsonify({'answer': answer, 'details': details})

    if re.search(r'\b(open|backlog)\b', q):
        sorted_open = sorted(eligible, key=lambda x: x.get('open', 0), reverse=True)[:5]
        answer = 'Highest open-issue backlog states:'
        details = [f"{r['state']}: {r['open']} open ({r['backlog_rate']:.1f}% backlog)" for r in sorted_open]
        return jsonify({'answer': answer, 'details': details})

    if re.search(r'\b(compare)\b', q):
        answer = f'Comparison summary for {matched_type or "all issue types"}: {len(eligible)} states with data.'
        details = [
            f"Best: {ranked[0]['state']} (score {ranked[0]['composite_score']:.1f})" if ranked else 'Best: N/A',
            f"Median success rate: {sorted([r['success_rate'] for r in eligible])[len(eligible)//2]:.1f}%" if eligible else 'Median success rate: N/A'
        ]
        return jsonify({'answer': answer, 'details': details})

    # Default summary
    if not ranked:
        return jsonify({'answer': 'No issue data available for this question.', 'details': []})

    avg_success = sum(r['success_rate'] for r in eligible) / len(eligible)
    avg_score = sum(r['composite_score'] for r in eligible) / len(eligible)
    answer = f'Quality snapshot for {matched_type or "all issue types"}: average success {avg_success:.1f}%, average composite score {avg_score:.1f}.'
    details = [
        f"Top: {ranked[0]['state']} ({ranked[0]['composite_score']:.1f})",
        f"Lowest: {ranked[-1]['state']} ({ranked[-1]['composite_score']:.1f})"
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
               MAX(CASE WHEN title LIKE '% Q1 2026%' THEN metric_value ELSE NULL END) as current_metric
        FROM issues
        WHERE state_id = ?
        GROUP BY issue_type
    ''', (state_id,))
    type_data = {row['issue_type']: dict(row) for row in cursor.fetchall()}

    # Nationwide dup claim rates for ranking (lower = better)
    cursor.execute('''
        SELECT s.id as state_id,
               MAX(CASE WHEN i.title LIKE '% Q1 2026%' AND i.issue_type = 'duplicate_claims'
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
                   MAX(CASE WHEN i.title LIKE '% Q1 2026%' THEN i.metric_value END) as cur
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
                   MAX(CASE WHEN i.title LIKE '% Q1 2026%' THEN i.metric_value END) as current_metric,
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
