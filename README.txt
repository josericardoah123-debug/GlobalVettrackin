# LabTrack — Field Operations Platform
### Laboratory equipment delivery & mileage reimbursement system

---

## QUICK START

### Windows
1. Double-click `START_WINDOWS.bat`
2. Browser opens automatically at http://localhost:5000
3. Done!

### Mac / Linux
1. Open Terminal in this folder
2. Run: `chmod +x START_MAC_LINUX.sh && ./START_MAC_LINUX.sh`
3. Open http://localhost:5000 in your browser

---

## REQUIREMENTS
- **Python 3.8+** — download at https://www.python.org/downloads/
  - Windows: check "Add Python to PATH" during install
- **Flask** — installed automatically by the startup script
- Any modern browser (Chrome, Firefox, Edge, Safari)

---

## WHAT'S INCLUDED

```
labtrack/
├── server.py              ← Backend server + database logic
├── labtrack.db            ← SQLite database (created on first run)
├── START_WINDOWS.bat      ← Windows launcher
├── START_MAC_LINUX.sh     ← Mac/Linux launcher
├── README.txt             ← This file
└── static/
    └── index.html         ← Frontend app (runs in browser)
```

---

## FEATURES

**Admin panel (open in any browser on your computer):**
- 📊 Dashboard — live technician status, pending approvals, low stock alerts
- 🚗 Trips — full log with route map on every trip, click any row to see the map
- 📦 Inventory — equipment catalog, stock levels, serial numbers
- 🏥 Clients — hospitals, clinics, labs with full delivery history
- 👷 Technicians — unlimited, add as many as you need
- ⚙️ Settings — configure reimbursement rate per km

**Employee app (the 📱 tab in the app):**
- Simulates the mobile experience for any technician
- Select client + equipment, start trip, GPS tracks km live
- End trip → saves to database automatically
- Reimbursement calculated instantly

---

## SHARING WITH YOUR TEAM (same WiFi / office network)

To let employees on other computers or phones access the app:

1. Find your computer's local IP address:
   - Windows: open Command Prompt, type `ipconfig`, look for "IPv4 Address"
   - Mac: System Settings → Network → your IP
2. They open: `http://YOUR-IP:5000` in their browser
   - Example: `http://192.168.1.45:5000`

---

## DATA & BACKUPS

Your data is stored in `labtrack.db` — a single file.
To back up: just copy `labtrack.db` somewhere safe.
To restore: replace the file and restart the server.

---

## DEPLOYING TO THE INTERNET (for remote access from anywhere)

When you're ready to access it from outside your office:

**Easiest option — Render.com (free tier):**
1. Create an account at render.com
2. Upload this folder
3. Set start command: `python server.py`
4. Your app will have a public URL like `https://labtrack-xxxx.onrender.com`

**Other options:** Railway.app, Heroku, a VPS (DigitalOcean, Hetzner)

Estimated cost: $0–$10/month depending on the plan.

---

## CUSTOMIZATION

- **Change company name:** Edit `static/index.html`, search for "LabTrack"
- **Change reimbursement rate:** Settings tab in the app
- **Add your real technicians:** Technicians tab → + Add technician
- **Add your real clients:** Clients tab → + Add client
- **Add your real equipment:** Inventory tab → + Add equipment

The sample data (Carlos, Lucía, Roberto, etc.) can be deleted once you add your real data.

---

Built with Python/Flask + SQLite + React
All code is yours — no licenses, no subscriptions.
