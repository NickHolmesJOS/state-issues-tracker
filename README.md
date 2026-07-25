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

## Claims Data Analysis (CSV)

A dedicated **Claims Data** section analyzes the real Medicaid provider-spending
CSV at `Data/medicaid-provider-spending.csv`.

- Because the file is very large (multi-GB), it is **streamed** and only a
  bounded **sample** of rows is read (configurable via the `sample` selector on
  the page or the `CLAIMS_SAMPLE_ROWS` environment variable).
- Computes real spending totals (paid, patients, claim lines) plus a monthly
  spend trend and top HCPCS codes / providers by spend.
- Flags data-quality issues: missing provider NPIs, duplicate claim rows,
  invalid HCPCS codes, per-claim-line payment outliers, non-positive paid
  amounts, and invalid claim months.
- **Customer-focused analytics** that turn those findings into action:
  - **Financial Exposure at Risk** — the dollar amount sitting on flagged rows,
    broken down by issue type (a recovery/audit target).
  - **Spend Concentration** — how much of total spend the top 1% / 10% / top-10
    providers account for, to focus audits where the money is.
  - **Year-over-Year Spend** — annual totals with YoY growth to spot anomalies.
  - **Highest-Risk Providers** — providers ranked by data-quality flag rate.
  - **Costliest Codes (Paid per Line)** — HCPCS codes with the highest average
    payment per line, as pricing/mispricing review candidates.
  - **Spending by Clinical Category** — HCPCS/CPT codes rolled up into clinical
    categories (drugs, surgery, radiology, DME, E/M, etc.) to compare where the
    money goes and how average cost-per-line differs by service type.
  - **Provider Peer-Comparison Outliers** — compares each provider's average
    payment-per-line for a procedure code against the code-wide peer average and
    flags providers billing far above their peers (potential up-coding), with a
    drill-down explaining exactly why each is an outlier.
- Most tables have inline **drill-down** buttons that reveal the actual offending
  rows and a plain-English explanation of why each is a problem.
- **Optimization & Overspending view** (`GET /claims/optimize`) turns the findings
  into an action plan:
  - **Total Optimization Potential** — recoverable/avoidable dollars, split into
    duplicate-claim payments, per-line payment outliers, and above-peer overspending.
  - **Prioritized Action Items** — ranked by dollar impact with a concrete step each.
  - **Biggest Overspending Providers** — dollars each provider paid above the peer
    average for the same codes (peer-benchmark excess, self-excluded).
  - **Spend Heatmap** — top providers × clinical category, colored by dollars, to
    spot spending hotspots at a glance.
- **Claims Data Assistant (chatbot)** — a floating chat widget on the `/claims`
  page answers natural-language questions (totals, top providers/codes, peer
  outliers, overspending, exposure, optimization, data quality, dates, etc.).
  It is *grounded on the analyzed sample*: `claims_chatbot.py` uses the computed
  sample summary as its knowledge base (no external LLM), so every answer reflects
  the real sampled data. Endpoint: `POST /api/claims/chat` with `{question, sample}`.
- Pages/endpoints: `GET /claims` (dashboard), `GET /claims/optimize` (optimization
  view) and `GET /api/claims/data` (JSON). Add `&refresh=1` to bypass the cache.

This feature is additive and does not affect the existing state-based tracker.

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
