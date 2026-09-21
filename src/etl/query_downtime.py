from __future__ import annotations
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
import pandas as pd

DOWNTIME_DIR = Path(r"\\FBN-FS01\GLOBAL\_A\AtthaphanP\INNOVIZ\OEE\Downtime_Entry\Downtime_Record")
PRODUCTION_DAY_START = dt_time(7, 0)
DAY_SHIFT_START = dt_time(7, 0)
NIGHT_SHIFT_START = dt_time(19, 0)
REQUIRED_COLUMNS = ["Type Downtime", "Detail", "EN Check In", "Timestamp Check In", "EN Check Out", "Timestamp Check Out", "Status"]

def get_machine_files() -> dict[str, Path]:
    if not DOWNTIME_DIR.exists():
        raise FileNotFoundError(f"Directory not found: {DOWNTIME_DIR}")
    return {file.stem.strip(): file for file in sorted(DOWNTIME_DIR.glob("*.csv")) }
    
def _read_csv_file(file_path: Path) -> pd.DataFrame:
    for encoding in ["utf-8-sig", "utf-8", "cp874", "tis-620"]:
        try:
            return pd.read_csv(file_path, encoding=encoding,)
        except UnicodeDecodeError:
            pass
    raise RuntimeError(f"Cannot read CSV: {file_path}")

def _clean_dataframe(df: pd.DataFrame, file_path: Path, machine_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = (df.columns .astype(str) .str.strip())
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"{file_path.name} missing columns: {missing}")
    for col in ["Type Downtime", "Detail", "Status"]:
        df[col] = (df[col].fillna("").astype(str).str.strip())
    df["Status"] = (df["Status"].str.upper().str.strip())
    df["Timestamp Check In"] = pd.to_datetime(df["Timestamp Check In"], dayfirst=True, errors="coerce")
    df["Timestamp Check Out"] = pd.to_datetime(df["Timestamp Check Out"], dayfirst=True, errors="coerce")
    df["Machine Name"] = machine_name
    df["Source File"] = file_path.name
    df = df[df["Timestamp Check In"].notna()].copy()
    return (df.sort_values("Timestamp Check In").reset_index(drop=True))

def read_all_downtime() -> pd.DataFrame:
    frames = []
    for machine_name, file_path in get_machine_files().items():
        try:
            raw_df = _read_csv_file(file_path)
            machine_df = _clean_dataframe(raw_df, file_path, machine_name)
            if not machine_df.empty: frames.append(machine_df)
        except Exception as exc:
            print(f"[WARNING] {file_path.name}: {exc}")
    if not frames:
        return pd.DataFrame()
    return (pd.concat(frames,ignore_index=True).sort_values("Timestamp Check In").reset_index(drop=True))

def get_production_window(production_date: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(datetime.combine(production_date, PRODUCTION_DAY_START))
    end = start + timedelta(days=1)
    return start, end

def get_shift(timestamp: pd.Timestamp) -> str:
    current_time = timestamp.time()
    if (DAY_SHIFT_START <= current_time < NIGHT_SHIFT_START):
        return "DAY"
    return "NIGHT"

def get_downtime_events_by_date(production_date: date) -> pd.DataFrame:
    df = read_all_downtime()
    if df.empty:
        return pd.DataFrame()
    window_start, window_end = (get_production_window(production_date))
    events = []
    for _, row in df.iterrows():
        event_start = row["Timestamp Check In"]
        event_end = row["Timestamp Check Out"]
        if pd.isna(event_start):
            continue
        status = str(row["Status"]).upper().strip()
        if pd.isna(event_end):
            if status == "OPENED":
                event_end = window_end
            else:
                continue
        start_clip = max(event_start, window_start)
        end_clip = min(event_end, window_end)
        if end_clip <= start_clip:
            continue
        duration_hr = (end_clip - start_clip).total_seconds() / 3600
        events.append({
            "Machine Name": row["Machine Name"],
            "Type Downtime": row["Type Downtime"],
            "Detail": row["Detail"],
            "EN Check In": row.get("EN Check In",""),
            "EN Check Out": row.get("EN Check Out",""),
            "Start_DateTime": start_clip,
            "End_DateTime": end_clip,
            "Original Check In": event_start,
            "Original Check Out": row["Timestamp Check Out"],
            "Downtime(hr)": round(duration_hr, 4),
            "Shift": get_shift(start_clip),
            "Production Date": production_date,
            "Status": status,
            "Source File": row["Source File"]
        })
        
    if not events:
        return pd.DataFrame()
    return (pd.DataFrame(events).sort_values(["Machine Name", "Start_DateTime",]).reset_index(drop=True))

def merge_intervals(intervals: list[tuple [pd.Timestamp, pd.Timestamp]]):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = (merged[-1])
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end,),)
        else:
            merged.append((start, end,))
    return merged

def calculate_unique_downtime_hours(machine_df: pd.DataFrame) -> float:
    if machine_df.empty:
        return 0.0
    intervals = []
    for _, row in machine_df.iterrows():
        start = row["Start_DateTime"]
        end = row["End_DateTime"]
        if (pd.isna(start) or pd.isna(end)):
            continue
        if end <= start:
            continue
        intervals.append((start, end))
    merged = merge_intervals(intervals)
    total_seconds = sum((end - start).total_seconds() for start, end in merged)
    return round(total_seconds / 3600, 2)

def summarize_downtime_type(downtime_df: pd.DataFrame, machine_name: str) -> dict[str, float]:
    if downtime_df.empty:
        return {}
    machine_df = downtime_df[downtime_df["Machine Name"] == machine_name]
    if machine_df.empty:
        return {}
    summary = (machine_df.groupby("Type Downtime")["Downtime(hr)"].sum().sort_values(ascending=False))
    return {
        downtime_type: round(float(hour), 2)
        for downtime_type, hour in summary.items()
    }
    
def get_downtime_by_date(production_date: date):
    machine_files = (get_machine_files())
    downtime_df = (get_downtime_events_by_date(production_date))
    downtime_data = {}
    downtime_type = {}
    for machine_name in (machine_files.keys()):
        if downtime_df.empty:
            downtime_data[machine_name] = 0.0
            downtime_type[machine_name] = {}
            continue
        machine_df = downtime_df[downtime_df["Machine Name"] == machine_name]
        downtime_data[machine_name] = (calculate_unique_downtime_hours(machine_df))
        downtime_type[machine_name] = (summarize_downtime_type(downtime_df, machine_name,))
    return downtime_data, downtime_type, downtime_df

def get_downtime_yesterday():
    production_date = (date.today() - timedelta(days=1))
    downtime_data, downtime_type, downtime_df = get_downtime_by_date(production_date)
    return downtime_data, downtime_type, downtime_df, production_date

# if __name__ == "__main__":
#     downtime_data, downtime_type, downtime_df, production_date = get_downtime_yesterday()
#     print("Production Date:",production_date)
#     print("\nDowntime Data")
#     for machine, hour in (downtime_data.items()):
#         print(f"{machine:15s}: "f"{hour:.2f} hr")
#     print("\nDowntime Type")
#     for machine, values in (downtime_type.items()):
#         print(machine,values)
#     print("\nDowntime DF")
#     print(downtime_df.to_string(index=False)
#         if not downtime_df.empty
#         else "Empty DataFrame"
#     )