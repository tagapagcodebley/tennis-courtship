"""
Watches Princes Gardens Tennis Courts (play.tennis.com.au) for court
openings inside a set of desired time windows, and emails when a
qualifying slot appears.

Designed to be run periodically (e.g. every 30 min) by Windows Task
Scheduler -- see run_watcher.ps1 / register_task.ps1. Each run does a
single check and exits; it remembers what it already notified about in
state.json so it doesn't spam the same still-open slot every run.
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

VENUE_SLUG = "PrincesGardensTennisCourts"
BASE_URL = "https://play.tennis.com.au"
SESSIONS_URL = f"{BASE_URL}/v0/VenueBooking/{VENUE_SLUG}/GetVenueSessions"
BOOKING_URL = f"{BASE_URL}/{VENUE_SLUG}/Booking/BookByDate"

TIMEZONE = ZoneInfo("Australia/Sydney")
WEEKS_AHEAD = 2
MIN_DURATION_MINUTES = 60

# Desired windows per weekday, as (start, end) in "HH:MM", 24h.
# Monday = 0 ... Sunday = 6
DESIRED_WINDOWS: dict[int, list[tuple[str, str]]] = {
    0: [("16:30", "19:30")],  # Monday
    1: [("16:30", "19:30")],  # Tuesday
    2: [("16:30", "19:30")],  # Wednesday
    3: [("16:30", "19:30")],  # Thursday
    4: [("08:00", "09:00"), ("16:30", "19:30")],  # Friday
    5: [("08:00", "19:30")],  # Saturday
    6: [("08:00", "19:30")],  # Sunday
}

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "state.json"
LOG_FILE = SCRIPT_DIR / "watcher.log"
BOOKED_DATES_FILE = SCRIPT_DIR / "booked_dates.txt"
MAX_LOG_BYTES = 100 * 1024  # trim watcher.log to this size, dropping oldest lines

# If you already have a booking on a given day (per booked_dates.txt), also
# skip this many following days (1 = skip the booked day and the day after).
SKIP_DAYS_AFTER_EXISTING_BOOKING = 1

EMAIL_FROM = os.environ.get("TENNIS_GMAIL_USER")
EMAIL_APP_PASSWORD = os.environ.get("TENNIS_GMAIL_APP_PASSWORD")
EMAIL_TO = [
    addr.strip()
    for addr in os.environ.get("TENNIS_NOTIFY_TO", "bjsesquivel@gmail.com").split(",")
    if addr.strip()
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class OpenSlot:
    court: str
    day: date
    start_min: int
    end_min: int

    @property
    def key(self) -> str:
        return f"{self.court}|{self.day.isoformat()}|{self.start_min}-{self.end_min}"

    def start_str(self) -> str:
        return _minutes_to_hhmm(self.start_min)

    def end_str(self) -> str:
        return _minutes_to_hhmm(self.end_min)

    def duration_minutes(self) -> int:
        return self.end_min - self.start_min

    def booking_url(self) -> str:
        return f"{BOOKING_URL}#?date={self.day.isoformat()}&role=guest"


def _minutes_to_hhmm(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _hhmm_to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


# ----------------------------------------------------------------------
# Fetching + parsing
# ----------------------------------------------------------------------

def fetch_sessions(start: date, end: date) -> dict:
    params = {
        "resourceID": "",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "roleId": "",
        "_": str(int(datetime.now().timestamp() * 1000)),
    }
    response = requests.get(SESSIONS_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


BOOKABLE_CATEGORY = 0  # Sessions with this category are open/unbooked slots
                        # (rendered on the site as clickable "Book at ..." links).
                        # Category 1000 ("Booking") means someone already booked it.


def find_open_slots(
    data: dict, now: datetime, excluded_dates: set[date] = frozenset()
) -> list[OpenSlot]:
    """Sessions with Category 0 are the open, unbooked slots. We merge
    adjacent ones into contiguous free ranges, intersect with the
    desired windows for that weekday, and keep ones long enough to book.
    Days in excluded_dates (e.g. days you already have a booking on, per
    booked_dates.txt) are skipped entirely.
    """
    open_slots: list[OpenSlot] = []

    for resource in data["Resources"]:
        court_name = resource["Name"]
        for day_entry in resource["Days"]:
            day = datetime.fromisoformat(day_entry["Date"]).date()
            if day in excluded_dates:
                continue
            windows = DESIRED_WINDOWS.get(day.weekday())
            if not windows:
                continue

            bookable = sorted(
                (s["StartTime"], s["EndTime"])
                for s in day_entry["Sessions"]
                if s["Category"] == BOOKABLE_CATEGORY
            )
            free_ranges = _merge(bookable)

            for desired_start_str, desired_end_str in windows:
                desired_start = _hhmm_to_minutes(desired_start_str)
                desired_end = _hhmm_to_minutes(desired_end_str)

                # Don't alert on times already in the past today.
                if day == now.date():
                    current_minutes = now.hour * 60 + now.minute
                    desired_start = max(desired_start, current_minutes)

                for free_start, free_end in free_ranges:
                    overlap_start = max(free_start, desired_start)
                    overlap_end = min(free_end, desired_end)
                    if overlap_end - overlap_start >= MIN_DURATION_MINUTES:
                        open_slots.append(
                            OpenSlot(court_name, day, overlap_start, overlap_end)
                        )

    return open_slots


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge sorted, possibly-adjacent/overlapping intervals."""
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ----------------------------------------------------------------------
# State (dedup notifications across runs)
# ----------------------------------------------------------------------

def load_state() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def save_state(keys: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(keys), indent=2))


def load_booked_dates() -> set[date]:
    """Reads booked_dates.txt: one YYYY-MM-DD per line, blank lines and
    lines starting with # ignored. Missing file just means no bookings."""
    if not BOOKED_DATES_FILE.exists():
        return set()

    booked_dates = set()
    for lineno, line in enumerate(BOOKED_DATES_FILE.read_text().splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            booked_dates.add(date.fromisoformat(line))
        except ValueError:
            log(f"WARNING: skipping unparseable line {lineno} in booked_dates.txt: {line!r}")
    return booked_dates


# ----------------------------------------------------------------------
# Notification
# ----------------------------------------------------------------------

def send_email(new_slots: list[OpenSlot], all_slots: list[OpenSlot]) -> None:
    if not EMAIL_FROM or not EMAIL_APP_PASSWORD:
        raise RuntimeError(
            "TENNIS_GMAIL_USER / TENNIS_GMAIL_APP_PASSWORD environment "
            "variables are not set -- cannot send email. See README.md."
        )

    lines = ["New court opening(s) at Princes Gardens Tennis Courts:", ""]
    for slot in sorted(new_slots, key=lambda s: (s.day, s.start_min)):
        lines.append(
            f"  {slot.day.strftime('%a %d %b %Y')}  {slot.court}  "
            f"{slot.start_str()}-{slot.end_str()} "
            f"({slot.duration_minutes()} min)"
        )
        lines.append(f"    Book: {slot.booking_url()}")

    if len(all_slots) > len(new_slots):
        lines.append("")
        lines.append("All currently open qualifying slots:")
        for slot in sorted(all_slots, key=lambda s: (s.day, s.start_min)):
            lines.append(
                f"  {slot.day.strftime('%a %d %b %Y')}  {slot.court}  "
                f"{slot.start_str()}-{slot.end_str()}"
            )

    body = "\n".join(lines)
    msg = MIMEText(body)
    msg["Subject"] = f"Tennis court opening: {len(new_slots)} new slot(s)"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(EMAIL_TO)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def log(message: str) -> None:
    timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def trim_log_file() -> None:
    """Drops the oldest lines from watcher.log if it's grown past
    MAX_LOG_BYTES. Runs once at the start of each invocation, so the file
    only ever gets meaningfully over the cap by about one run's worth of
    lines before the next run trims it back down."""
    if not LOG_FILE.exists():
        return
    data = LOG_FILE.read_bytes()
    if len(data) <= MAX_LOG_BYTES:
        return

    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    kept_bytes = sum(len(line.encode("utf-8")) for line in lines)
    first_kept = 0
    while kept_bytes > MAX_LOG_BYTES and first_kept < len(lines):
        kept_bytes -= len(lines[first_kept].encode("utf-8"))
        first_kept += 1

    LOG_FILE.write_text("".join(lines[first_kept:]), encoding="utf-8")


def main() -> int:
    trim_log_file()
    now = datetime.now(TIMEZONE)
    today = now.date()
    end = today + timedelta(weeks=WEEKS_AHEAD)

    try:
        data = fetch_sessions(today, end)
    except requests.RequestException as exc:
        log(f"ERROR fetching sessions: {exc}")
        return 1

    booked_dates = {
        d for d in load_booked_dates()
        if d + timedelta(days=SKIP_DAYS_AFTER_EXISTING_BOOKING) >= today
    }
    excluded_dates: set[date] = set()
    for booked_day in booked_dates:
        for offset in range(SKIP_DAYS_AFTER_EXISTING_BOOKING + 1):
            excluded_dates.add(booked_day + timedelta(days=offset))
    if booked_dates:
        log(f"Booked on {sorted(d.isoformat() for d in booked_dates)}; "
            f"excluding those day(s) + {SKIP_DAYS_AFTER_EXISTING_BOOKING} after.")

    open_slots = find_open_slots(data, now, excluded_dates)
    current_keys = {slot.key for slot in open_slots}

    previous_keys = load_state()
    new_keys = current_keys - previous_keys
    new_slots = [slot for slot in open_slots if slot.key in new_keys]

    log(f"Checked {today} .. {end}: {len(open_slots)} open qualifying slot(s), "
        f"{len(new_slots)} new.")

    if new_slots:
        for slot in sorted(new_slots, key=lambda s: (s.day, s.start_min)):
            log(f"  NEW: {slot.day} {slot.court} {slot.start_str()}-{slot.end_str()}")
        try:
            send_email(new_slots, open_slots)
            log(f"Notification email sent to {', '.join(EMAIL_TO)}.")
        except Exception as exc:
            log(f"ERROR sending email: {exc}")
            return 1

    save_state(current_keys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
