# ASX Price Sensitive Announcements — Daily Enriched Report

Automatically fetches every morning's ASX **price sensitive announcements**
and enriches them with **market cap**, **sector**, **price**, and **daily change**
from Yahoo Finance. Outputs a clean, searchable HTML report.

Runs free via GitHub Actions. No API keys required.

---

## What you get

- Every price sensitive announcement from that morning
- Each row enriched with: Market Cap · GICS Sector · Industry · Live Price · Daily % Change
- Searchable and sortable HTML report
- Published to a personal GitHub Pages URL automatically each weekday at 10am AEST
- Report also committed to this repo as `report.html` for archiving

---

## Setup (5 minutes)

### Step 1 — Create a GitHub account
Go to [github.com](https://github.com) and sign up (free).

### Step 2 — Create a new repository
1. Click **New repository** (green button on your dashboard)
2. Name it: `asx-monitor`
3. Set to **Public** (required for free GitHub Pages)
4. Click **Create repository**

### Step 3 — Upload these files
Upload all files from this folder into the new repo:
- `fetch_announcements.py`
- `requirements.txt`
- `.github/workflows/daily.yml`
- `README.md`

You can drag-and-drop them on the GitHub web interface, or use the
"uploading an existing file" link on the repo page.

> **Important:** The `.github/workflows/` folder must be created exactly
> as shown. GitHub needs the workflow file at that exact path.

### Step 4 — Enable GitHub Pages
1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **GitHub Actions**
3. Click **Save**

### Step 5 — Enable workflow permissions
1. Go to **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

### Step 6 — Run it manually to test
1. Go to **Actions** tab in your repo
2. Click **ASX Daily Announcements Report** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Wait ~30 seconds
5. Your report will be live at:
   `https://YOUR-USERNAME.github.io/asx-monitor/report.html`

---

## Schedule

The workflow runs automatically:
- **Every weekday (Mon–Fri) at 10:00 AM AEST** (midnight UTC)
- You can also trigger it manually anytime via the Actions tab

---

## Running locally

```bash
pip install requests
python fetch_announcements.py
# Opens report.html — open in your browser
```

---

## Notes

- **Data sources:** ASX.com.au (announcements) · Yahoo Finance (market data)
- **No API keys needed** — both sources are free and public
- **Price sensitive only** — filters to market-sensitive announcements
- The ASX endpoint is undocumented but has been stable for years
- If ASX changes their API, the script prints an error and produces an
  empty report rather than crashing silently
- Not financial advice
