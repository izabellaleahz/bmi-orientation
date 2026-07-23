# Rotation Orientation Site

A static, single-page orientation site for incoming rotation students. No build
step, no backend — just HTML/CSS/JS. Works when opened directly or hosted on
GitHub Pages / any static host.

Tabs: **Schedule** · **Past Rotations** · **Seminars & Talks** · **Logistics** ·
**Around SF** · **Timeline & FAQ**. The schedule filters by track and exports any
session to Google Calendar or `.ics`. Light + dark theme (follows the viewer's
system setting, with a manual toggle bottom-right).

## Files

```
index.html               The page (structure + logic — you rarely edit this)
data/content.js          ← EDIT THIS: schedule, rotations, SF recs, people, logistics, timeline, FAQ
data/seminars.js         AUTO-GENERATED seminar list (don't edit by hand)
data/seminars.json       Same data as JSON (for reuse elsewhere)
scripts/refresh_seminars.py   Pulls seminars from feeds into data/seminars.js
scripts/sources.json     ← EDIT THIS: which seminar feeds to pull
```

## Editing content

Open **`data/content.js`** — it's commented and holds everything the page shows:
the heading, the schedule (`EVENTS` + `TRACKS`), past rotations, SF recommendations,
the people directory, logistics checklists, the rotation timeline, and the FAQ.
Save and reload the page. That's the whole workflow.

Dates are `"YYYY-MM-DD"`, times are 24-hour `"HH:MM"`. Set your timezone once in
`CONFIG` (`timezone` for calendar exports, `tzLabel` for the label shown next to times).

## Previewing

- **Simplest:** double-click `index.html` (everything loads locally, seminars included).
- **Server (matches production):**
  ```bash
  cd orientation-schedule
  python3 -m http.server 8000
  # open http://localhost:8000
  ```

## Seminars — keeping the list fresh

The seminar list is generated, not hand-edited. Point the script at feeds in
`scripts/sources.json`, then run it:

```bash
python3 scripts/refresh_seminars.py
```

It reads **iCal (`.ics`)** and **RSS/Atom** feeds, keeps upcoming events within
`days_ahead`, optionally filters by `keywords`, and rewrites `data/seminars.js`.
Standard library only — no `pip install` needed (Python 3.9+).

Finding feeds: most UCSF/department/institute calendars have a **"Subscribe" or
"iCal"** link — that URL goes in `sources.json` as `type: "ics"` (preferred, since
iCal carries real start/end times). RSS works too but often lacks times. Replace the
`REPLACE_WITH_..._FEED_URL` placeholders with real feed URLs; sources that fail to
fetch are skipped with a warning, so a bad URL won't break the others.

Keep it current automatically with cron:

```bash
0 6 * * *  cd /path/to/orientation-schedule && python3 scripts/refresh_seminars.py
```

## Deploying to GitHub Pages

1. Put this folder in a repo and push.
2. Repo **Settings → Pages** → deploy from your branch, root folder.
3. If you re-run the refresh script, commit the updated `data/seminars.js`.
   (Or run it in a GitHub Action on a schedule and commit the result.)
