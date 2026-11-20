# OEE Dashboard

Automatically generates a daily **OEE report** (Availability × Performance × Quality)
for each physical machine and displays it on a web dashboard.
It also includes a **Downtime Entry** page where operators record machine downtime.

## How it works

```
Downtime Entry page ──► Downtime CSV (shared drive)  ─┐
FITS (yield, first-pass, active time) ────────────────┤
                                                       ▼
                main_daily.py  (Task Scheduler, every day 08:00)
                  1. src/etl/query_downtime.py        read downtime CSV
                  2. src/etl/query_yield.py           read yield + active time from FITS
                  3. src/calculation/oee_cal.py       calculate A / P / Q / OEE per machine
                  4. src/analytics/smart_insight.py   summary / focus / action
                  5. src/storage/snapshot.py          write <HISTORY PATH>/YYYY-MM-DD.json
                                                       ▼
                app.py  (web server)  ──►  OEE Dashboard  (select a date to load its JSON)
```

## Production day

One production day is one calendar day: production date **D** = D 00:00 → D+1 00:00.
Breaks (all on day D): 00:00–01:00, 04:30–05:00, 11:00–12:00, 16:30–17:00.
Breaks total 3 hr, so `PLANNED_TIME = 21` hr.
Example: production date **2026-11-16** = 2026-11-16 00:00 → 2026-11-17 00:00.

> Snapshots created before this change (up to 2026-11-18) use the old window
> (D-1 19:00 → D 19:00) and are not recalculated.
> `main_daily.py` runs at **08:00** and always calculates **yesterday's** production day.
> The dashboard checks the JSON folder every 1 minute and switches to the newest day as soon as its JSON appears.

## Formulas

| KPI                                                                                      | Formula                                                                                                                                                                              |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Availability                                                                             | Operating time / Planned time, where Operating = Actual Run time. Planned = Actual Run + Downtime + Unknown; Unknown (no FITS data and no downtime keyed in) is not operating time |
| Performance                                                                              | Σ(output_i / IDEAL_SPEED_i) / Operating time                                                                                                                                        |
| Quality                                                                                  | Pass / Total at the last OPN (First-Pass Yield from FITS)                                                                                                                            |
| OEE                                                                                      | A × P × Q                                                                                                                                                                          |
| If a machine's data is incomplete (missing downtime file, invalid downtime rows,         |                                                                                                                                                                                      |
| FITS data issues, ...), its KPIs show **DATA INCOMPLETE** and the reason is listed |                                                                                                                                                                                      |
| under *Data Quality* on the dashboard.                                                 |                                                                                                                                                                                      |

## Machines and processes

Configured in `config/config.ini` (OPN list, `IDEAL_SPEED`, targets, FITS station → machine).

| Line                                                           | Processes                                                                                       | Machines               |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ---------------------- |
| AB2B                                                           | AB2B + AB2B_POST_TEST (same machines, different programs)                                       | AB2B01, AB2B02         |
| AA                                                             | AA_FAS_SAS + AA_FAS_SAS_POST_OVEN + AA_TP + AA_TP_POST_OVEN (same machines, different programs) | AA01, AA02             |
| IEOL Bring-up / CRS                                            | IEOL_BRINGUP + IEOL_CRS (same machines, different programs)                                     | IEOL_BRINGUP_CRS01–03 |
| IEOL Short                                                     | IEOL_SHORT                                                                                      | IEOL_SR01–03          |
| IEOL Long                                                      | IEOL_LONG                                                                                       | IEOL_LR01–03          |
| IEOL flow: IEOL_BRINGUP → IEOL_SHORT → IEOL_LONG → IEOL_CRS |                                                                                                 |                        |

## Setup (server)

1. Install dependencies
   ```
   pip install -r requirements.txt
   ```
2. Set Windows Environment Variables| Name                | Required | Note                           |
   | ------------------- | -------- | ------------------------------ |
   | `FITS_USER`       | yes      | FITS account                   |
   | `FITS_PASSWORD`   | yes      | FITS password                  |
   | `FITS_URL`        | no       | default: Fabrinet FITS service |
   | `FITS_PROJECT_ID` | no       | default `729`                |
3. Check paths in `config/config.ini`
   - `[HISTORY] PATH` – folder for the daily JSON files
   - `[DOWNTIME] record_path`, `type_path` – downtime CSV folders
4. Run the daily report once by hand and confirm the JSON file is created
   ```
   python main_daily.py
   ```
5. Windows Task Scheduler
   - Trigger: daily at **08:00**
   - Action: `python main_daily.py`
   - **Start in**: the repository folder
   - Run as a user that can access the shared drive and has the FITS variables
   - Settings: *If the task fails, restart every 15 minutes* (3–4 attempts)
6. Web server
   ```
   waitress-serve --host 0.0.0.0 --port 5000 app:app
   ```

## Web pages and API

| Path                                   | Description                                     |
| -------------------------------------- | ----------------------------------------------- |
| `/`                                  | OEE Dashboard                                   |
| `/downtime`                          | Downtime Entry and Downtime History             |
| `/api/oee/dates`                     | Dates that have a JSON snapshot                 |
| `/api/oee/dashboard?date=YYYY-MM-DD` | Snapshot of the selected date (default: latest) |

> The Downtime Entry page has no login. Use it on the internal network only.
