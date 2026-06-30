# Development Guide - State Issues Tracker

## Setting Up Your Development Environment

### Prerequisites
- Python 3.8 or higher
- Git
- VS Code (recommended)
- A text editor

### Initial Setup

1. **Navigate to project directory:**
```bash
cd /Users/nicholasholmes/Side_Project
```

2. **Create virtual environment (recommended):**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Run the application:**
```bash
python3 app.py
```

5. **Open in browser:**
```
http://localhost:5000
```

## Project Structure Guide

### Backend Structure (`app.py`)

```python
# 1. Imports and Configuration
from flask import Flask, render_template, request, jsonify
app = Flask(__name__)

# 2. Database Functions
def get_db()              # Get DB connection
def init_db()             # Initialize with schema & dummy data

# 3. Routes (Pages)
@app.route('/')           # Dashboard
@app.route('/state/<id>')  # State details
@app.route('/compare')    # Comparison page
@app.route('/analytics')  # Analytics page

# 4. API Endpoints (AJAX)
@app.route('/api/compare')          # Get comparison data
@app.route('/api/issue/<id>/update') # Update issue status

# 5. Main execution
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
```

### Template Structure (`templates/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `base.html` | Base layout | Navigation, footer, scripts |
| `dashboard.html` | Main page | State cards, statistics |
| `state_detail.html` | State view | Issue list, filters, status dropdown |
| `compare.html` | Comparison | Tag filter, comparison table, charts |
| `analytics.html` | Analytics | Statistics cards, visualization charts |

### Static Files Structure (`static/`)

```
static/
├── css/
│   └── style.css          # 1000+ lines of custom styling
└── js/
    └── (future scripts)
```

## Common Development Tasks

### Adding a New Page

1. **Create route in `app.py`:**
```python
@app.route('/newpage')
def new_page():
    return render_template('newpage.html')
```

2. **Create template `templates/newpage.html`:**
```html
{% extends "base.html" %}
{% block title %}New Page Title{% endblock %}
{% block content %}
    <div class="container-lg py-5">
        <!-- Your content here -->
    </div>
{% endblock %}
```

3. **Add link in `base.html` navigation:**
```html
<li class="nav-item">
    <a class="nav-link" href="/newpage">New Page</a>
</li>
```

### Adding a New Tag

1. **Edit `app.py` in `init_db()` function:**
```python
tags = ['existing tags', 'new_tag_name']
for tag in tags:
    cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag,))
```

2. **Delete `issues.db` to reset database**
3. **Restart Flask app to regenerate data**

### Adding New Issues

1. **Edit `app.py` in `init_db()` function:**
```python
dummy_issues = [
    ('StateName', 'Issue Title', 'Description', 'status', 'priority'),
    # Add more tuples here
]
```

2. **Update `tag_mapping` to match issue count:**
```python
tag_mapping = {
    0: [0, 2],  # Issue 1: tags at indices 0 and 2
    1: [1, 4],  # Issue 2: tags at indices 1 and 4
    # Add more mappings
}
```

3. **Reset database and restart app**

### Modifying Styling

1. **Edit `static/css/style.css`**
2. **Refresh browser (Ctrl+R or Cmd+R)**
3. **Clear cache if needed (Ctrl+Shift+Delete)**

### Creating a New API Endpoint

```python
@app.route('/api/newendpoint', methods=['GET', 'POST'])
def new_endpoint():
    db = get_db()
    cursor = db.cursor()
    
    # Get data
    cursor.execute('SELECT * FROM your_table')
    data = cursor.fetchall()
    db.close()
    
    # Return JSON
    return jsonify([dict(row) for row in data])
```

Call from JavaScript:
```javascript
fetch('/api/newendpoint')
    .then(response => response.json())
    .then(data => console.log(data))
    .catch(error => console.error('Error:', error));
```

## Database Operations

### Query Examples

#### Get all states:
```python
cursor.execute('SELECT * FROM states ORDER BY name')
states = cursor.fetchall()
```

#### Get issues for a state:
```python
cursor.execute('''
    SELECT i.*, GROUP_CONCAT(t.name, ', ') as tags
    FROM issues i
    LEFT JOIN issue_tags it ON i.id = it.issue_id
    LEFT JOIN tags t ON it.tag_id = t.id
    WHERE i.state_id = ?
    GROUP BY i.id
''', (state_id,))
issues = cursor.fetchall()
```

#### Update issue status:
```python
cursor.execute('''
    UPDATE issues 
    SET status = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
''', (new_status, issue_id))
db.commit()
```

#### Get statistics:
```python
cursor.execute('''
    SELECT COUNT(*) as total,
           SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
           SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open
    FROM issues
''')
stats = dict(cursor.fetchone())
```

### Database Reset

To start fresh with new dummy data:
```bash
rm issues.db
python3 app.py
```

## Frontend Development

### Adding Bootstrap Classes

Common Bootstrap utilities used:
```html
<!-- Grid -->
<div class="container-lg">
    <div class="row">
        <div class="col-md-6">Half width on medium screens</div>
    </div>
</div>

<!-- Cards -->
<div class="card">
    <div class="card-body">Content</div>
</div>

<!-- Buttons -->
<button class="btn btn-primary">Primary</button>
<button class="btn btn-outline-secondary">Outline</button>

<!-- Badges -->
<span class="badge bg-success">Done</span>

<!-- Alerts -->
<div class="alert alert-info">Info message</div>
```

### Creating Charts with Chart.js

Example from `compare.html`:
```javascript
const ctx = document.getElementById('myChart').getContext('2d');
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['State 1', 'State 2'],
        datasets: [{
            label: 'Success Rate',
            data: [75, 85],
            backgroundColor: '#198754'
        }]
    },
    options: {
        responsive: true
    }
});
```

## Debugging Tips

### Browser Console
Open browser developer tools (F12) to:
- See JavaScript errors
- Log data with `console.log()`
- Test JavaScript code
- Network debugging

### Flask Debug Mode
Already enabled! Features:
- Automatic reloading on code changes
- Interactive debugger on errors
- Debug toolbar (optional)

### Add Debug Output
```python
# In Python
print(f"Debug: {variable}")

# In HTML
{{ variable }}

# In JavaScript
console.log('Debug:', data);
```

## Testing Checklist

Before deployment, verify:

- [ ] Dashboard loads all states
- [ ] Each state card shows correct statistics
- [ ] State detail page displays all issues
- [ ] Filtering by status works (All, Done, Open, Cancelled)
- [ ] Changing issue status updates correctly
- [ ] Comparison page loads without errors
- [ ] Comparison charts render correctly
- [ ] Tag filter changes data
- [ ] Analytics page displays all statistics
- [ ] Charts render on analytics page
- [ ] Responsive design works on mobile
- [ ] No console errors in browser
- [ ] All links navigate correctly
- [ ] Navigation menu works on mobile

## Performance Optimization

### Current Performance
- Database queries are efficient with proper WHERE clauses
- CSS is minified and optimized
- No unnecessary JavaScript

### Future Optimizations
1. Add database indexing for faster queries
2. Cache frequently accessed data
3. Use CDN for static files
4. Implement lazy loading for images
5. Add service worker for offline support

## Security Considerations

### Current Implementation
- ✅ SQL injection protection (parameterized queries)
- ✅ No sensitive data exposure
- ✅ CSRF tokens not needed (read-only forms)
- ✅ Input validation

### Recommended Additions
- [ ] User authentication
- [ ] Authorization checks
- [ ] Rate limiting
- [ ] HTTPS (automatic on Render)
- [ ] Content Security Policy headers
- [ ] Input sanitization

## Git Workflow

### Committing Changes
```bash
# Check status
git status

# Stage files
git add .

# Commit
git commit -m "Brief description of changes"

# Push to GitHub
git push origin main
```

### Creating Branches
```bash
# Create new branch
git checkout -b feature/new-feature

# Make changes
# Commit changes

# Push branch
git push origin feature/new-feature

# Create pull request on GitHub
```

## Deployment Preparation

### Before Deploying to Render:

1. **Update requirements.txt** with all dependencies
2. **Test locally** thoroughly
3. **Create Procfile** (already done)
4. **Push to GitHub**
5. **Connect Render to GitHub**
6. **Deploy!**

## Useful Resources

### Documentation
- [Flask Documentation](https://flask.palletsprojects.com)
- [Bootstrap 5 Docs](https://getbootstrap.com/docs/5.0)
- [Chart.js Documentation](https://www.chartjs.org/docs/latest/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [Render Docs](https://render.com/docs)

### Learning Resources
- [Python for Web Development](https://realpython.com)
- [Web Design Best Practices](https://www.smashingmagazine.com)
- [Git & GitHub Guide](https://github.github.com/training-kit/)

## Common Issues & Solutions

### Issue: Port 5000 already in use
```bash
# Find process using port
lsof -i :5000

# Kill process
kill -9 <PID>
```

### Issue: Static files not updating
- Clear browser cache (Ctrl+Shift+Delete)
- Restart Flask server
- Check file path in template

### Issue: Database locked error
- Ensure only one instance of Flask is running
- Delete `issues.db` and restart

### Issue: Template not found error
- Check file name spelling
- Verify file is in `/templates/` directory
- Restart Flask server

## Next Steps

1. ✅ Understand current project structure
2. ✅ Make small customizations
3. ✅ Test thoroughly
4. ✅ Deploy to Render
5. ✅ Gather user feedback
6. ✅ Plan Phase 2 features

---

Happy developing! 🚀
