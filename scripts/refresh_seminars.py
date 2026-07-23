#!/usr/bin/env python3
"""
Refresh the seminar list for the orientation site.

Reads feed sources from scripts/sources.json, pulls upcoming events from
iCal (.ics) and RSS/Atom feeds, and writes data/seminars.js (which the page
loads via a <script> tag) and data/seminars.json.

No third-party packages required — standard library only (Python 3.9+).

Usage:
    python3 scripts/refresh_seminars.py
    python3 scripts/refresh_seminars.py --config scripts/sources.json

Cron example (every day at 6am):
    0 6 * * *  cd /path/to/orientation-schedule && python3 scripts/refresh_seminars.py
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")

UA = "orientation-seminar-refresh/1.0 (+static site)"


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# iCal parsing
# --------------------------------------------------------------------------- #
def unfold_ical(text):
    """Undo RFC 5545 line folding (continuation lines start with space/tab)."""
    out = []
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def ical_unescape(v):
    return (v.replace("\\n", "\n").replace("\\N", "\n")
             .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def parse_ical_dt(value, params, default_tz):
    """Return a timezone-aware datetime (or None). Handles Z, TZID, floating, date-only."""
    value = value.strip()
    if not value:
        return None
    # date-only, e.g. 20260916
    if re.fullmatch(r"\d{8}", value):
        dt = datetime.strptime(value, "%Y%m%d")
        return dt.replace(tzinfo=default_tz)
    m = re.fullmatch(r"(\d{8})T(\d{6})(Z)?", value)
    if not m:
        return None
    dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    if m.group(3) == "Z":
        return dt.replace(tzinfo=timezone.utc)
    tzid = params.get("TZID")
    if tzid and ZoneInfo:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            pass
    return dt.replace(tzinfo=default_tz)  # floating -> assume site tz


def parse_ical(text, default_tz):
    events = []
    cur = None
    for line in unfold_ical(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        bits = name_part.split(";")
        key = bits[0].upper()
        params = {}
        for p in bits[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.upper()] = v
        if key == "DTSTART":
            cur["start"] = parse_ical_dt(value, params, default_tz)
        elif key == "DTEND":
            cur["end"] = parse_ical_dt(value, params, default_tz)
        elif key == "SUMMARY":
            cur["title"] = ical_unescape(value).strip()
        elif key == "LOCATION":
            cur["location"] = ical_unescape(value).strip()
        elif key == "URL":
            cur["url"] = value.strip()
        elif key == "DESCRIPTION":
            cur["desc"] = ical_unescape(value).strip()
    return events


# --------------------------------------------------------------------------- #
# RSS / Atom parsing (best-effort; time often absent)
# --------------------------------------------------------------------------- #
def strip_ns(tag):
    return tag.split("}", 1)[-1].lower()


def parse_rss(text, default_tz):
    events = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return events

    items = []
    for el in root.iter():
        if strip_ns(el.tag) in ("item", "entry"):
            items.append(el)

    for it in items:
        rec = {}
        for child in it:
            t = strip_ns(child.tag)
            txt = (child.text or "").strip()
            if t == "title":
                rec["title"] = txt
            elif t in ("link",) and not rec.get("url"):
                rec["url"] = (child.get("href") or txt).strip()
            elif t in ("pubdate", "published", "updated", "date", "start") and txt:
                dt = parse_rss_date(txt, default_tz)
                if dt:
                    rec["start"] = dt
        if rec.get("title"):
            events.append(rec)
    return events


def parse_rss_date(s, default_tz):
    s = s.strip()
    fmts = ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=default_tz)
            return dt
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def matches_keywords(title, desc, keywords):
    if not keywords:
        return True
    hay = (title + " " + desc).lower()
    return any(k.lower() in hay for k in keywords)


def is_excluded(title, desc, excludes):
    if not excludes:
        return False
    hay = (title + " " + desc).lower()
    return any(k.lower() in hay for k in excludes)


def main():
    ap = argparse.ArgumentParser(description="Refresh orientation seminar list.")
    ap.add_argument("--config", default=os.path.join(HERE, "sources.json"))
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    tz_name = cfg.get("timezone", "America/Los_Angeles")
    default_tz = ZoneInfo(tz_name) if ZoneInfo else timezone.utc
    days_ahead = int(cfg.get("days_ahead", 60))
    max_items = int(cfg.get("max_items", 40))
    global_excludes = cfg.get("exclude_keywords", [])

    now = datetime.now(default_tz)
    horizon = now + timedelta(days=days_ahead)

    collected = []
    for src in cfg.get("sources", []):
        name = src.get("name", "Seminar")
        url = src.get("url")
        stype = src.get("type", "ics").lower()
        keywords = src.get("keywords", [])
        excludes = global_excludes + src.get("exclude", [])
        if not url:
            continue
        try:
            text = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name}: fetch failed ({exc})", file=sys.stderr)
            continue

        raw = parse_ical(text, default_tz) if stype == "ics" else parse_rss(text, default_tz)
        kept = 0
        for ev in raw:
            start = ev.get("start")
            title = ev.get("title", "").strip()
            if not start or not title:
                continue
            start_local = start.astimezone(default_tz)
            if not (now - timedelta(hours=12) <= start_local <= horizon):
                continue
            if not matches_keywords(title, ev.get("desc", ""), keywords):
                continue
            if is_excluded(title, ev.get("desc", ""), excludes):
                continue
            end_local = ev.get("end").astimezone(default_tz) if ev.get("end") else None
            collected.append({
                "title": title,
                "date": start_local.strftime("%Y-%m-%d"),
                "start": start_local.strftime("%H:%M"),
                "end": end_local.strftime("%H:%M") if end_local else "",
                "series": name,
                "location": ev.get("location", ""),
                "speaker": "",
                "url": ev.get("url", "") or src.get("page", ""),
            })
            kept += 1
        print(f"  · {name}: {kept} upcoming", file=sys.stderr)

    # dedup by (title, date, start); sort; cap
    seen, unique = set(), []
    for e in sorted(collected, key=lambda x: (x["date"], x["start"], x["title"])):
        k = (e["title"].lower(), e["date"], e["start"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(e)
    unique = unique[:max_items]

    generated = now.strftime("%Y-%m-%d")
    payload = {"generated": generated, "items": unique}

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "seminars.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    banner = ("/* AUTO-GENERATED by scripts/refresh_seminars.py — do not edit by hand. */\n"
              "window.SEMINARS = ")
    with open(os.path.join(DATA_DIR, "seminars.js"), "w", encoding="utf-8") as fh:
        fh.write(banner + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n")

    print(f"Wrote {len(unique)} seminars (generated {generated}).", file=sys.stderr)


if __name__ == "__main__":
    main()
