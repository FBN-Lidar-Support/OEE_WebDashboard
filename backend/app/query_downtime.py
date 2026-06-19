import pandas as pd
from datetime import date, timedelta, datetime
import time
SHEET_ID = "1GX-QmKKZivETF-5s77m0LNAfT0M8LxKm7i2nVqtxUY8"
RAW_GID = "126900875"
RAW_DATA_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={RAW_GID}"
)
def safe_float(value):
    try:
        if pd.isna(value):
            return 0.0
        value = str(value).strip()
        if value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0
def convert_production_date(value):
    """
    Convert Production Date from Google Sheet.
    Support:
    46191
    46191.0
    18/6/2026
    2026-06-18
    """
    if pd.isna(value):
        return None
    try:
        number = float(value)
        if number > 30000:
            return pd.to_datetime(
                number,
                unit="D",
                origin="1899-12-30",
                errors="coerce"
            ).date()
    except Exception:
        pass
    try:
        return pd.to_datetime(
            value,
            dayfirst=True,
            errors="coerce"
        ).date()
    except Exception:
        return None
def parse_timestamp(value):
    """
    Google Form Timestamp.
    Example:
    18/6/2026, 15:32:51
    """
    if pd.isna(value):
        return None
    try:
        return pd.to_datetime(
            value,
            dayfirst=True,
            errors="coerce"
        ).to_pydatetime()
    except Exception:
        return None
def parse_end_datetime(start_datetime, end_time_value):
    """
    ใช้ Timestamp เป็น Start Date
    แล้วเอา End DownTime ที่เป็นเวลา มารวมเป็น End DateTime
    Example:
    start = 2026-06-18 15:32:51
    end_time = 17:00:00
    end = 2026-06-18 17:00:00
    ถ้า End Time น้อยกว่า Start Time เช่น
    start = 2026-06-18 23:30:00
    end_time = 00:30:00
    จะถือว่า End เป็นวันถัดไป
    """
    if start_datetime is None:
        return None
    if pd.isna(end_time_value):
        return None
    text = str(end_time_value).strip()
    if text == "":
        return None
    try:
        end_time = pd.to_datetime(
            text,
            errors="coerce"
        ).time()
        end_datetime = datetime.combine(
            start_datetime.date(),
            end_time
        )
        if end_datetime < start_datetime:
            end_datetime = end_datetime + timedelta(days=1)
        return end_datetime
    except Exception:
        return None
def hours_to_time_format(hours):
    """
    1.45 -> 1:27
    2.0 -> 2:00
    """
    try:
        total_minutes = round(float(hours) * 60)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}:{m:02d}"
    except Exception:
        return "0:00"
def merge_intervals(intervals):
    """
    Merge overlapping intervals.
    Example:
    15:32 - 17:00
    16:34 - 18:00
    16:37 - 18:00
    Result:
    15:32 - 18:00
    """
    if not intervals:
        return []
    intervals = sorted(
        intervals,
        key=lambda x: x[0]
    )
    merged = [intervals[0]]
    for current_start, current_end in intervals[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:
            merged[-1] = (
                last_start,
                max(last_end, current_end)
            )
        else:
            merged.append(
                (current_start, current_end)
            )
    return merged
def calculate_unique_downtime_hours(machine_df):
    intervals = []
    for _, row in machine_df.iterrows():
        start_datetime = row.get("Start_DateTime")
        end_datetime = row.get("End_DateTime")
        if start_datetime is None or end_datetime is None:
            continue
        if pd.isna(start_datetime) or pd.isna(end_datetime):
            continue
        if end_datetime <= start_datetime:
            continue
        intervals.append(
            (start_datetime, end_datetime)
        )
    merged_intervals = merge_intervals(intervals)
    total_hours = 0.0
    for start_dt, end_dt in merged_intervals:
        total_hours += (
            end_dt - start_dt
        ).total_seconds() / 3600
    return total_hours
def read_raw_downtime_sheet():
    cache_url = RAW_DATA_URL + "&t=" + str(int(time.time()))
    df = pd.read_csv(cache_url)
    print("=" * 50)
    # print("Read Raw Downtime Sheet")
    # print("Columns:", df.columns.tolist())
    # print("Rows:", len(df))
    df["Production Date"] = df["Production Date"].apply(
        convert_production_date
    )
    df["Start_DateTime"] = df["ประทับเวลา"].apply(
        parse_timestamp
    )
    df["End_DateTime"] = df.apply(
        lambda row: parse_end_datetime(
            row["Start_DateTime"],
            row["End DownTime"]
        ),
        axis=1
    )
    df["Calculated_Downtime_Hours"] = df.apply(
        lambda row: (
            (row["End_DateTime"] - row["Start_DateTime"]).total_seconds() / 3600
            if row["Start_DateTime"] is not None
            and row["End_DateTime"] is not None
            and row["End_DateTime"] > row["Start_DateTime"]
            else 0
        ),
        axis=1
    )
    df["Calculated_Downtime_Display"] = df["Calculated_Downtime_Hours"].apply(
        hours_to_time_format
    )
    return df
def get_downtime_yesterday():
    df = read_raw_downtime_sheet()
    target_date = date.today() - timedelta(days=1)
    df = df[
        df["Production Date"] == target_date
    ]
    result = {}
    machines = (
        df["Machine (เครื่อง)"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )
    for machine in machines:
        machine_df = df[
            df["Machine (เครื่อง)"].astype(str).str.strip() == machine
        ]
        downtime = calculate_unique_downtime_hours(
            machine_df
        )
        result[machine] = downtime
    # print("Target Date:", target_date)
    # print("Downtime Result:")
    # print(result)
    return result, target_date

def get_downtime_history_by_machine(machine_name: str, production_date):
    df = read_raw_downtime_sheet()
    df = df[
        (df["Machine (เครื่อง)"].astype(str).str.strip() == machine_name)
        & (df["Production Date"] == production_date)
    ]
    df = df.sort_values(
        by="Start_DateTime",
        ascending=True
    )
    history = []
    for _, row in df.iterrows():
        # print(df.columns.tolist())
        start_datetime = row.get("Start_DateTime")
        end_datetime = row.get("End_DateTime")
        start_text = ""
        end_text = ""
        if start_datetime is not None and not pd.isna(start_datetime):
            start_text = start_datetime.strftime("%H:%M:%S")
        if end_datetime is not None and not pd.isna(end_datetime):
            end_text = end_datetime.strftime("%H:%M:%S")
        downtime_hours = safe_float(
            row.get("Calculated_Downtime_Hours", 0)
        )
        history.append({
            "timestamp": str(row.get("ประทับเวลา", "")),
            "production_date": str(row.get("Production Date", "")),
            "en": str(row.get("EN", "")),
            "machine": str(row.get("Machine (เครื่อง)", "")),
            # "start_downtime": start_text,
            "end_downtime": end_text,
            "type_downtime": str(row.get("Type Downtime", "")),
            "shift": str(row.get("Shift (กะ)", "")),
            "total_downtime": round(downtime_hours, 2),
            "total_downtime_display": hours_to_time_format(downtime_hours),
            "remark": str(row.get("Remark", "")),
        })
        # print(history)
    return history