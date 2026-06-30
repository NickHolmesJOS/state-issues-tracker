# State Issues Tracker Dashboard

A modern web application for tracking, managing, and comparing issues across different states. Built with Flask, SQLite, and modern web technologies.

## Features

✨ **Core Features:**
- **Dashboard**: Overview of all states and their issue statistics
- **State Details**: View and manage issues for each state
- **Issue Management**: Mark issues as done, cancelled, or open
- **Tagging System**: Categorize issues with custom tags
- **Compare**: Compare issues across states by performance metrics
- **Analytics**: System-wide statistics and insights
- **Responsive Design**: Works on desktop, tablet, and mobile devices

## Project Structure

```
├── app.py                 # Flask application and routes
├── requirements.txt       # Python dependencies
├── static/
│   └── css/
│       └── style.css     # Modern styling
├── templates/
│   ├── base.html         # Base template with navigation
│   ├── dashboard.html    # Main dashboard view
│   ├── state_detail.html # State-specific issues
│   ├── compare.html      # Cross-state comparison
│   └── analytics.html    # Analytics and insights
└── issues.db            # SQLite database (auto-generated)
```

## Installation

### Prerequisites
- Python 3.7+
- pip

### Setup

1. Clone the repository:
```bash
cd /Users/nicholasholmes/Side_Project
```

2. Create a virtual environment (optional but recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Application

1. Start the Flask development server:
```bash
python app.py
```

2. Open your browser and navigate to:
```
http://localhost:5000
```

The database will be automatically created with dummy data on first run.

## Usage

### Dashboard
- View overview of all states
- See total issues, completed, open, and cancelled counts
- Quick access to individual state details

### State Details
- View all issues for a specific state
- Filter issues by status (All, Done, Open, Cancelled)
- Update issue status with the status dropdown
- View issue tags and priority levels

### Compare
- Select a tag to filter comparison data
- See success rates across all states
- View performance metrics in table and chart format
- Identify which states have the most successful outcomes

### Analytics
- System-wide statistics
- Issue status distribution charts
- Tag usage statistics
- Visual representation of success rates

## Database Schema

### Tables:
- **states**: State information
- **issues**: Individual issues with status and priority
- **tags**: Available tags for categorization
- **issue_tags**: Many-to-many relationship between issues and tags

## Dummy Data

The application includes pre-populated data with:
- 6 states (California, Texas, Florida, New York, Pennsylvania, Illinois)
- 18 sample issues across all states
- Multiple status types (open, done, cancelled)
- 6 different tags for categorization
- Various priority levels

## Deployment to Render

This project is already configured for Render using [render.yaml](render.yaml).

### 1) Push this project to GitHub

```bash
cd /Users/nicholasholmes/Side_Project
git init
git add .
git commit -m "Prepare Flask app for Render deployment"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

### 2) Deploy on Render

1. In Render, click New + and choose Blueprint.
2. Connect your GitHub repository.
3. Render will read [render.yaml](render.yaml) automatically.
4. Click Apply and deploy.

### Notes

- A persistent disk is configured at `/app/data`.
- SQLite will be stored at `/app/data/issues.db` in production.
- `gunicorn` is already listed in [requirements.txt](requirements.txt).

## Technologies Used

- **Backend**: Flask (Python web framework)
- **Database**: SQLite
- **Frontend**: HTML5, CSS3, JavaScript
- **UI Components**: Bootstrap 5
- **Icons**: Bootstrap Icons
- **Charts**: Chart.js
- **Styling**: Custom CSS with modern gradients and animations

## Future Enhancements

- User authentication and authorization
- Export reports to PDF/Excel
- Real-time notifications
- Advanced filtering and search
- Issue templates
- Bulk operations
- API documentation
- Mobile app
- Performance optimization
- Caching

## License

This project is provided as-is for internal use.

## Support

For issues or questions, please contact your development team.
