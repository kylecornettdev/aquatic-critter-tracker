# 🐠 Aquatic Critter Fish Tracker

A local web dashboard that scrapes Aquatic Critter's freshwater arrival pages,
tracks every fish species, and predicts when they'll show up next.

---

## Quick Setup

### 1. Install Python (if you don't have it)
Download from https://python.org — make sure to check "Add Python to PATH" during install.

### 2. Install dependencies
Open a command prompt in this folder and run:

```
pip install requests beautifulsoup4
```

### 3. Run the server
In the same folder, run:

```
python server.py
```

You'll see:
```
🐟  Aquatic Critter Tracker running at http://localhost:8765
```

### 4. Open the dashboard
Open your browser and go to: **http://localhost:8765**

### 5. Do your first scrape
Click **"Update Now"** on the page. It will crawl all the arrival pages
(this takes about 30–60 seconds the first time). Subsequent updates are faster.

---

## Files

| File | What it does |
|------|-------------|
| `server.py` | Local web server — serves the dashboard and triggers scrapes |
| `scraper.py` | The actual scraper — fetches pages and extracts fish names |
| `index.html` | The dashboard UI |
| `fish_data.json` | Your fish database (auto-created on first scrape) |

---

## Automated Daily Scraping (Windows Task Scheduler)

To have it scrape automatically every day without clicking the button:

### Option A: Scrape-only (no browser needed)

1. Create a file called `run_scrape.bat` in this folder with this content:

```bat
@echo off
cd /d "C:\path\to\your\aquatic-tracker"
python scraper.py
```

(Replace `C:\path\to\your\aquatic-tracker` with the actual folder path)

2. Open **Task Scheduler** (search for it in Start menu)
3. Click **Create Basic Task**
4. Name it: `Aquatic Critter Fish Scraper`
5. Trigger: **Daily** at whatever time you want (e.g., 8:00 AM)
6. Action: **Start a program**
7. Program: browse to your `run_scrape.bat` file
8. Finish ✓

The scraper will run daily and update `fish_data.json`. Next time you
open the dashboard, it'll reflect the latest data.

### Option B: Auto-start the server on login

If you want the dashboard always accessible at http://localhost:8765:

1. Create `start_server.bat`:
```bat
@echo off
cd /d "C:\path\to\your\aquatic-tracker"
start /min python server.py
```

2. Press **Win+R**, type `shell:startup`, press Enter
3. Copy (or shortcut) `start_server.bat` into that folder

The server will start minimized when you log in.

---

## How the Prediction Works

For fish that have appeared 2+ times, the tracker calculates the average
interval between appearances (in days) and projects the next visit forward
from the last known date.

- 🟡 **Yellow / "~Xd"** = expected within 2 weeks
- 🔴 **Red / "overdue"** = past the predicted date (watch for it soon!)
- Rows highlighted in green = due within 7 days

---

## Troubleshooting

**"Could not connect to local server"**
→ Make sure `python server.py` is still running in your terminal.

**Fish names look wrong / lots of junk entries**
→ The site layout may have changed. Open an issue or re-run — the scraper
  is conservative but not perfect on novel page layouts.

**0 fish found after scraping**
→ The site may have added Cloudflare bot protection that blocks even
  browser-mimicking requests. Try opening one of the arrival pages manually
  in your browser first (this sometimes clears the challenge), then re-scrape.

---

## Source
Data from [Aquatic Critter](https://aquaticcritter.com) — Nashville, TN
5009 Nolensville Pk · (615) 832-4541
