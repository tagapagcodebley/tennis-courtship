# Tennis Court Watcher

Watches [Princes Gardens Tennis Courts](https://play.tennis.com.au/PrincesGardensTennisCourts/)
for court openings and emails you when one appears.

It calls the booking site's own JSON API directly (`GetVenueSessions`) rather
than scraping HTML, so it's fast and reliable.

## What it watches for

Any court, at least a **60-minute** continuous opening, within:

- Mon-Thu: 16:30-19:30
- Fri: 08:00-09:00 and 16:30-19:30
- Sat-Sun: 08:00-19:30

Looks 2 weeks ahead. Edit `DESIRED_WINDOWS`, `MIN_DURATION_MINUTES`, or
`WEEKS_AHEAD` at the top of `watch_courts.py` to change any of this.

## One-time setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Generate a Gmail App Password (needed because Gmail blocks plain
   password SMTP login):
   - Go to https://myaccount.google.com/apppasswords (requires 2-Step
     Verification enabled on the Google account).
   - Create an app password named e.g. "tennis-watcher", copy the 16
     characters.

3. Copy `secrets.example.ps1` to `secrets.ps1` and fill in:
   - `TENNIS_GMAIL_USER` — the Gmail address sending the alert
   - `TENNIS_GMAIL_APP_PASSWORD` — the app password from step 2
   - `TENNIS_NOTIFY_TO` — where alerts go

   `secrets.ps1` stays local — don't share or commit it.

4. Test it manually:

   ```powershell
   .\run_watcher.ps1
   ```

   Check `watcher.log` for output. It should report how many qualifying
   open slots it found. It only emails when a *new* slot appears
   (tracked in `state.json`), so the first run may or may not send mail
   depending on current availability.

5. Register the recurring check (runs every 30 minutes via Windows Task
   Scheduler):

   ```powershell
   .\register_task.ps1
   ```

## Managing the scheduled task

```powershell
Get-ScheduledTask -TaskName TennisCourtWatcher        # check status
Start-ScheduledTask -TaskName TennisCourtWatcher        # run now
Unregister-ScheduledTask -TaskName TennisCourtWatcher -Confirm:$false   # remove
```

## Notes

- `state.json` remembers which open slots have already been emailed so
  you don't get a new email every 30 minutes for the same still-open
  slot. If a slot closes and later reopens, it's treated as new again.
- Booking still has to be done manually — the script only notifies, it
  doesn't book the court for you.
