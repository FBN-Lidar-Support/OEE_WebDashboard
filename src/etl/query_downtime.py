from __future__ import annotations
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
import pandas as pd

DOWNTIME_DIR = Path(r"\\FBN-FS01\GLOBAL\_A\AtthaphanP\INNOVIZ\OEE\Downtime_Entry\Downtime_Record")
PRODUCTION_DAY_START = dt_time(7, 0)
DAY_SHIFT_START = dt_time(7, 0)
NIGHT_SHIFT_START = dt_time(19, 0)
REQUIRED_COLUMNS = [
    "Type Downtime", "Detail", "EN Check In", "Timestamp Check In",
    "EN Check Out", "Timestamp Check Out", "Status"
]

# ============================================================
# 1. READ DOWNTIME CSV
# ============================================================
def get_machine_files() -> dict[str, Path]:
    if not DOWNTIME_DIR.is_dir():
        raise FileNotFoundError(f"Directory not found: {DOWNTIME_DIR}")
    machine_files = {}
    for line_dir in sorted(DOWNTIME_DIR.iterdir()):
        if not line_dir.is_dir() or line_dir.name.startswith("."):
            continue
        for file in sorted(line_dir.glob("*.csv")):
            if not file.is_file():
                continue
            machine = file.stem.strip()
            if machine in machine_files:
                raise ValueError(f"Duplicate machine: {machine}")
            machine_files[machine] = file
    return machine_files
def _read_csv_file(file_path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "cp874", "tis-620"):
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Cannot read CSV: {file_path}")
def _clean_dataframe(df: pd.DataFrame, file_path: Path, machine_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"{file_path.name} missing columns: {missing}")
    for col in ("Type Downtime", "Detail", "Status"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["Status"] = df["Status"].str.upper()
    for col in ("Timestamp Check In", "Timestamp Check Out"):
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    df["Machine Name"] = machine_name
    df["Source File"] = file_path.name
    if df["Timestamp Check In"].isna().any():
        raise ValueError(f"{file_path.name}: missing/invalid Timestamp Check In")
    return df.sort_values("Timestamp Check In").reset_index(drop=True)
def read_all_downtime() -> pd.DataFrame:
    frames = []
    for machine_name, file_path in get_machine_files().items():
        try:
            raw_df = _read_csv_file(file_path)
            machine_df = _clean_dataframe(raw_df, file_path, machine_name)
        except Exception as exc:
            raise RuntimeError(f"Cannot load downtime file {file_path.name}: {exc}") from exc
        if not machine_df.empty:
            frames.append(machine_df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        "Timestamp Check In"
    ).reset_index(drop=True)
# ============================================================
# 2. PRODUCTION WINDOW & BREAK TIME
# ============================================================
def get_production_window(production_date: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(datetime.combine(production_date, PRODUCTION_DAY_START))
    return start, start + timedelta(days=1)
def get_break_intervals(production_date: date) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    day = pd.Timestamp(production_date).normalize()
    next_day = day + pd.Timedelta(days=1)
    return [
        # Day Shift
        (day + pd.Timedelta(hours=11), day + pd.Timedelta(hours=12)),
        (day + pd.Timedelta(hours=16, minutes=30),
         day + pd.Timedelta(hours=17)),
        # Night Shift (next calendar day)
        (next_day, next_day + pd.Timedelta(hours=1)),
        (next_day + pd.Timedelta(hours=4, minutes=30),
         next_day + pd.Timedelta(hours=5))
    ]
def get_shift(timestamp: pd.Timestamp) -> str:
    current_time = timestamp.time()
    return "DAY" if DAY_SHIFT_START <= current_time < NIGHT_SHIFT_START else "NIGHT"
# ============================================================
# 3. MERGE OVERLAPPING DOWNTIME
# ============================================================
def merge_intervals(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]):
    if not intervals:
        return []
    merged = []
    for start, end in sorted(intervals, key=lambda pair: pair[0]):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (
                merged[-1][0],
                max(merged[-1][1], end)
            )
        else:
            merged.append((start, end))
    return merged
# ============================================================
# 4. CALCULATE EFFECTIVE DOWNTIME
# ============================================================
def _effective_hours(intervals, production_date: date) -> float:
    breaks = get_break_intervals(production_date)
    merged = merge_intervals(intervals)
    total_seconds = 0.0
    for start, end in merged:
        seconds = (end - start).total_seconds()
        for break_start, break_end in breaks:
            overlap_start = max(start, break_start)
            overlap_end = min(end, break_end)
            if overlap_start < overlap_end:
                seconds -= (overlap_end - overlap_start).total_seconds()
        total_seconds += max(seconds, 0.0)
    return round(total_seconds / 3600, 6)
# ============================================================
# 5. GET DOWNTIME EVENTS BY PRODUCTION DATE
# ============================================================
def get_downtime_events_by_date(production_date: date) -> pd.DataFrame:
    df = read_all_downtime()
    if df.empty:
        return pd.DataFrame()
    window_start, window_end = get_production_window(production_date)
    now = pd.Timestamp.now()
    events = []
    for _, row in df.iterrows():
        event_start = row["Timestamp Check In"]
        event_end = row["Timestamp Check Out"]
        status = row["Status"]
        # OPENED: use current time, capped at production day end
        if pd.isna(event_end):
            if status != "OPENED":
                raise ValueError(
                    f"{row['Source File']}: missing checkout for status {status}"
                )
            event_end = min(now, window_end)
        if event_end < event_start:
            raise ValueError(f"{row['Source File']}: checkout before check-in")
        # Clip to production window
        start_clip = max(event_start, window_start)
        end_clip = min(event_end, window_end)
        if end_clip <= start_clip:
            continue
        raw_hours = (end_clip - start_clip).total_seconds() / 3600
        effective_hours = _effective_hours(
            [(start_clip, end_clip)],
            production_date
        )
        events.append({
            "Machine Name": row["Machine Name"],
            "Type Downtime": row["Type Downtime"],
            "Detail": row["Detail"],
            "EN Check In": row.get("EN Check In", ""),
            "EN Check Out": row.get("EN Check Out", ""),
            "Start_DateTime": start_clip,
            "End_DateTime": end_clip,
            "Original Check In": event_start,
            "Original Check Out": row["Timestamp Check Out"],
            "Downtime(hr)": round(raw_hours, 4),
            "Effective Downtime(hr)": round(effective_hours, 4),
            "Shift": get_shift(start_clip),
            "Production Date": production_date,
            "Status": status,
            "Source File": row["Source File"]
        })
    if not events:
        return pd.DataFrame()
    return pd.DataFrame(events).sort_values(
        ["Machine Name", "Start_DateTime"]
    ).reset_index(drop=True)
# ============================================================
# 6. UNIQUE DOWNTIME PER MACHINE
# ============================================================
def calculate_unique_downtime_hours(
    machine_df: pd.DataFrame,
    production_date: date | None = None
) -> float:
    if machine_df.empty:
        return 0.0
    if production_date is None:
        production_date = machine_df["Production Date"].iloc[0]
    intervals = [
        (row["Start_DateTime"], row["End_DateTime"])
        for _, row in machine_df.iterrows()
        if pd.notna(row["Start_DateTime"])
        and pd.notna(row["End_DateTime"])
    ]
    window_start, window_end = get_production_window(production_date)
    intervals = [
        (max(start, window_start), min(end, window_end))
        for start, end in intervals
    ]
    return _effective_hours(intervals, production_date)
# ============================================================
# 7. DOWNTIME SUMMARY BY TYPE
# ============================================================
def summarize_downtime_type(
    downtime_df: pd.DataFrame,
    machine_name: str
) -> dict[str, float]:
    if downtime_df.empty:
        return {}
    machine_df = downtime_df[
        downtime_df["Machine Name"] == machine_name
    ]
    if machine_df.empty:
        return {}
    result = {}
    for downtime_type, group in machine_df.groupby("Type Downtime"):
        result[downtime_type] = calculate_unique_downtime_hours(group)
    return dict(
        sorted(result.items(), key=lambda item: item[1], reverse=True)
    )
# ============================================================
# 8. MAIN DOWNTIME FUNCTION
# ============================================================
def get_downtime_by_date(production_date: date):
    machine_files = get_machine_files()
    downtime_df = get_downtime_events_by_date(production_date)
    downtime_data = {}
    downtime_type = {}
    for machine_name in machine_files:
        if downtime_df.empty:
            downtime_data[machine_name] = 0.0
            downtime_type[machine_name] = {}
            continue
        machine_df = downtime_df[
            downtime_df["Machine Name"] == machine_name
        ]
        downtime_data[machine_name] = calculate_unique_downtime_hours(
            machine_df, production_date
        )
        downtime_type[machine_name] = summarize_downtime_type(
            downtime_df, machine_name
        )
    return downtime_data, downtime_type, downtime_df
def get_downtime_yesterday():
    production_date = date.today() - timedelta(days=1)
    downtime_data, downtime_type, downtime_df = get_downtime_by_date(
        production_date
    )
    return downtime_data, downtime_type, downtime_df, production_date