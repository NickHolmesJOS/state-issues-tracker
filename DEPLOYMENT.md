# Deployment Guide - State Issues Tracker

## Deploying to Render.com

This guide will walk you through deploying your State Issues Tracker to Render, a modern cloud platform.

### Prerequisites

1. **GitHub Account**: Create one at https://github.com if you don't have one
2. **Render Account**: Sign up at https://render.com
3. **Local Project**: This application

### Step 1: Prepare Your Project

#### 1.1 Create a Render configuration file

Create a file named `render.yaml` in your project root:

```yaml
services:
  - type: web
    name: state-issues-tracker
    env: python38
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: PYTHON_VERSION
        value: 3.8.18
```

#### 1.2 Update requirements.txt

Add Gunicorn for production:

```
Flask==3.0.3
Werkzeug==3.0.6
gunicorn==21.2.0
```

#### 1.3 Create a Procfile (optional but recommended)

Create a file named `Procfile`:

```
web: gunicorn app:app
```

#### 1.4 Create a .gitignore

```
venv/
*.pyc
__pycache__/
*.egg-info/
dist/
build/
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store
Thumbs.db
.env
.env.local
*.db
```

### Step 2: Push to GitHub

1. **Initialize git** (if not already done):
```bash
cd /Users/nicholasholmes/Side_Project
git init
git add .
git commit -m "Initial commit: State Issues Tracker"
```

2. **Create a GitHub repository**:
   - Go to https://github.com/new
   - Name it `state-issues-tracker`
   - Don't initialize with README (we have one)
   - Click "Create repository"

3. **Push your code**:
```bash
git remote add origin https://github.com/YOUR_USERNAME/state-issues-tracker.git
git branch -M main
git push -u origin main
```

### Step 3: Deploy on Render

1. **Sign in to Render**: https://render.com/dashboard

2. **Create a new Web Service**:
   - Click "New +" button
   - Select "Web Service"
   - Connect your GitHub account if not already connected
   - Select the `state-issues-tracker` repository
   - Click "Connect"

3. **Configure the Service**:
   - **Name**: `state-issues-tracker` (or your preferred name)
   - **Environment**: Select `Python 3.8` from dropdown
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Plan**: Select Free (or paid if you prefer)

4. **Set Environment Variables** (if needed):
   - Skip for now - not required for this app

5. **Create Web Service**:
   - Click "Create Web Service"
   - Render will start building and deploying

### Step 4: Verify Deployment

1. Wait for the build to complete (check the logs)
2. Once deployed, Render will provide you with a URL like: `https://state-issues-tracker.onrender.com`
3. Visit the URL to verify the application is running

### Step 5: Persistent Storage (Optional)

If you want to persist the SQLite database across deploys:

1. Go to your service dashboard on Render
2. Click "Disks" tab
3. Create a new disk:
   - **Name**: `db`
   - **Mounted Path**: `/app/data`
   - **Size**: 1 GB (free tier option)

4. Update `app.py` to use the persistent disk:
```python
import os
db_path = os.getenv('DB_PATH', '/app/data/issues.db') if os.path.exists('/app/data') else 'issues.db'
app.config['DATABASE'] = db_path
```

### Step 6: Automatic Deployments

By default, Render will automatically deploy whenever you push to GitHub:

1. Make changes locally
2. Commit and push to GitHub:
```bash
git add .
git commit -m "Your commit message"
git push origin main
```
3. Render will automatically rebuild and deploy

### Troubleshooting

**Issue: Build fails with import errors**
- Solution: Ensure all dependencies are in `requirements.txt`

**Issue: Database not found**
- Solution: The database is recreated on first run, so this should auto-resolve

**Issue: Static files not loading**
- Solution: Flask automatically serves static files - ensure the `/static` folder structure is correct

**Issue: Application crashes on deploy**
- Check the logs in Render dashboard for specific errors
- Verify all environment variables are set (if any are required)

### Domain Configuration (Optional)

To add a custom domain:

1. Go to your service on Render
2. Click "Settings"
3. Scroll to "Custom Domain"
4. Enter your domain and follow instructions
5. Update your domain's DNS records as directed

### Monitoring and Logs

1. **View Logs**: In Render dashboard, click your service, then "Logs"
2. **Monitor Performance**: Use Render's built-in metrics
3. **Error Alerts**: Set up alerts in the "Alerts" tab

### Database Backups

Since this uses SQLite:
- Download the database from the persistent disk manually if needed
- Consider migrating to PostgreSQL for production use

### Production Recommendations

1. **Enable HTTPS**: Render automatically enables this
2. **Add Authentication**: Consider adding user login
3. **Set DEBUG=False**: Update Flask config for production
4. **Use PostgreSQL**: For better production support
5. **Add Error Monitoring**: Integrate with Sentry for error tracking
6. **Performance Optimization**: Use CDN for static assets

### Quick Reference

| Item | Value |
|------|-------|
| Deployment Platform | Render.com |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |
| Python Version | 3.8+ |
| Database | SQLite (or PostgreSQL) |
| Free Tier Limit | App spins down after 15 min inactivity |

### Support

For more information:
- Render Documentation: https://render.com/docs
- Flask Documentation: https://flask.palletsprojects.com
- Gunicorn Documentation: https://gunicorn.org/

---

Your app is now ready to be deployed to Render! 🚀
