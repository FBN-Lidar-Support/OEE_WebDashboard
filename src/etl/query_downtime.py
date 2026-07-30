from __future__ import annotations
from datetime import date, datetime, time as dt_time, timedelta
from io import StringIO
import time
import pandas as pd
import requests

# ============================================================
# GOOGLE SHEET CONFIG
# ============================================================
SHEET_ID = "1GX-QmKKZivETF-5s77m0LNAfT0M8LxKm7i2nVqtxUY8"
RAW_GID = "126900875"
RAW_DATA_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={RAW_GID}"
)
MACHINES = ["AB2B", "AA", "IEOL"]
DAY_SHIFT_START = dt_time(7, 0)
NIGHT_SHIFT_START = dt_time(19, 0)
# ============================================================
# TEXT CLEANING
# ============================================================
def normalize_check_status(value) -> str | None:
    """
    แปลงค่า Check in / Check out ให้เป็นรูปแบบมาตรฐาน
    """
    if pd.isna(value):
        return None
    text = str(value).strip().lower()
    text = " ".join(text.split())
    check_in_values = {
        "check in",
        "checkin",
        "in",
        "start",
    }
    check_out_values = {
        "check out",
        "checkout",
        "out",
        "end",
    }
    if text in check_in_values:
        return "check in"
    if text in check_out_values:
        return "check out"
    return None
def parse_timestamp(value) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    text = str(value).strip().replace(",", "")
    return pd.to_datetime(
        text,
        dayfirst=True,
        errors="coerce",
    )
# ============================================================
# SHIFT / PRODUCTION DATE
# ============================================================
def get_shift(timestamp: pd.Timestamp) -> str:
    current_time = timestamp.time()
    if DAY_SHIFT_START <= current_time < NIGHT_SHIFT_START:
        return "DAY"
    return "NIGHT"
def get_production_date(timestamp: pd.Timestamp) -> date:
    if timestamp.time() < DAY_SHIFT_START:
        return (timestamp - timedelta(days=1)).date()
    return timestamp.date()
# ============================================================
# MERGE OVERLAPPING DOWNTIME
# ============================================================
def merge_intervals(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda interval: interval[0],)
    merged = [intervals[0]]
    for current_start, current_end in intervals[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged
def calculate_unique_downtime_hours(machine_df: pd.DataFrame) -> float:
    intervals = []
    for _, row in machine_df.iterrows():
        start_datetime = row.get("Start_DateTime")
        end_datetime = row.get("End_DateTime")
        if pd.isna(start_datetime) or pd.isna(end_datetime):
            continue
        if end_datetime <= start_datetime:
            continue
        intervals.append((start_datetime, end_datetime))
    merged_intervals = merge_intervals(intervals)
    total_hours = sum((end_dt - start_dt).total_seconds() / 3600
        for start_dt, end_dt in merged_intervals
    )
    return round(total_hours, 2)
# ============================================================
# READ GOOGLE SHEET
# ============================================================
def download_raw_sheet() -> pd.DataFrame:
    cache_url = RAW_DATA_URL + "&t=" + str(int(time.time()))
    try:
        response = requests.get(cache_url, timeout=30)
        response.encoding = "utf-8"
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Cannot connect to Google Sheets. "
            "Please check internet connection."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "Google Sheets request timeout."
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to read Google Sheets: {exc}"
        ) from exc
    if "<html" in response.text.lower():
        raise RuntimeError(
            "Google Sheets returned HTML instead of CSV. "
            "Please check the sheet sharing permission."
        )
    df = pd.read_csv(StringIO(response.text))
    # ลบช่องว่างในชื่อคอลัมน์
    df.columns = (df.columns.astype(str).str.strip())
    # print(df.to_string())
    return df
# ============================================================
# PAIR CHECK IN / CHECK OUT
# ============================================================
def pair_checkin_checkout(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    
    required_columns = {
        "Timestamp",
        "Machine Name",
        "Downtime Check in / Check out",
    }
    missing_columns = required_columns - set(raw_df.columns)
    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(sorted(missing_columns))
        )
    df = raw_df.copy()
    # หมายเลขแถวใน Google Sheet
    df["Source_Row"] = df.index + 2
    
    # สร้างคอลัมน์ที่ไม่มี
    optional_columns = [
        "EN",
        "Type Downtime",
        "Remark",
    ]
    for column in optional_columns:
        if column not in df.columns:
            df[column] = ""
    # Parse Timestamp
    df["Timestamp"] = df["Timestamp"].apply(parse_timestamp)
    # Clean Machine Name
    df["Machine Name"] = (df["Machine Name"].astype("string").str.strip().str.upper())
    # Clean Check Status
    df["Check_Status"] = df["Downtime Check in / Check out"].apply(normalize_check_status)
    # Clean other text
    for column in [
        "EN",
        "Type Downtime",
        "Remark",
    ]:
        df[column] = (df[column].fillna("").astype(str).str.strip())
    validation_rows = []
    # --------------------------------------------------------
    # Validate Timestamp
    # --------------------------------------------------------
    invalid_timestamp_df = df[df["Timestamp"].isna()]
    for _, row in invalid_timestamp_df.iterrows():
        validation_rows.append({
            "Source Row": row["Source_Row"],
            "Machine Name": row["Machine Name"],
            "Issue": "Invalid Timestamp",
            "Detail": "Cannot convert Timestamp to datetime",
        })
    # --------------------------------------------------------
    # Validate Machine
    # --------------------------------------------------------
    invalid_machine_df = df[
        ~df["Machine Name"].isin(MACHINES)
    ]
    for _, row in invalid_machine_df.iterrows():
        validation_rows.append({
            "Source Row": row["Source_Row"],
            "Machine Name": row["Machine Name"],
            "Issue": "Invalid Machine",
            "Detail": "Machine must be AB2B, AA or IEOL",
        })
    # --------------------------------------------------------
    # Validate Check Status
    # --------------------------------------------------------
    invalid_check_df = df[df["Check_Status"].isna()]
    for _, row in invalid_check_df.iterrows():
        validation_rows.append({
            "Source Row": row["Source_Row"],
            "Machine Name": row["Machine Name"],
            "Issue": "Invalid Downtime Check",
            "Detail": (
                f"Invalid value: {row['Downtime Check in / Check out']}"
            ),
        })
    # ใช้เฉพาะแถวที่ถูกต้อง
    valid_df = df[
        df["Timestamp"].notna()
        & df["Machine Name"].isin(MACHINES)
        & df["Check_Status"].notna()
    ].copy()
    valid_df = valid_df.sort_values(
        by=[
            "Timestamp",
            "Source_Row",
        ]
    ).reset_index(drop=True)
    # เก็บ Check in ล่าสุดของแต่ละเครื่อง
    active_checkins: dict[str, pd.Series] = {}
    downtime_rows = []
    for _, row in valid_df.iterrows():
        machine = row["Machine Name"]
        status = row["Check_Status"]
        timestamp = row["Timestamp"]
        # ====================================================
        # CHECK IN
        # ====================================================
        if status == "check in":
            if machine in active_checkins:
                previous_row = active_checkins[machine]
                validation_rows.append({
                    "Source Row": row["Source_Row"],
                    "Machine Name": machine,
                    "Issue": "Duplicate Check in",
                    "Detail": (
                        "A previous Check in is still waiting "
                        "for Check out. New Check in replaces it."
                    ),
                })
                # เก็บรายการเก่าเป็น Waiting Check out
                downtime_rows.append({
                    "Machine Name": machine,
                    "EN": previous_row["EN"],
                    "Downtime Type": previous_row[
                        "Type Downtime"
                    ],
                    "Start_DateTime": previous_row[
                        "Timestamp"
                    ],
                    "End_DateTime": pd.NaT,
                    "Calculated_Downtime_Hours": pd.NA,
                    "Production Date": get_production_date(
                        previous_row["Timestamp"]
                    ),
                    "Shift": get_shift(
                        previous_row["Timestamp"]
                    ),
                    "Remark": previous_row["Remark"],
                    "Status": "Waiting Check out",
                    "Check In Row": previous_row[
                        "Source_Row"
                    ],
                    "Check Out Row": pd.NA,
                })
            active_checkins[machine] = row
        # ====================================================
        # CHECK OUT
        # ====================================================
        elif status == "check out":
            if machine not in active_checkins:
                validation_rows.append({
                    "Source Row": row["Source_Row"],
                    "Machine Name": machine,
                    "Issue": "Missing Check in",
                    "Detail": (
                        "Check out found without previous "
                        "Check in for this machine."
                    ),
                })
                continue
            checkin_row = active_checkins.pop(machine)
            start_datetime = checkin_row["Timestamp"]
            end_datetime = timestamp
            if end_datetime <= start_datetime:
                validation_rows.append({
                    "Source Row": row["Source_Row"],
                    "Machine Name": machine,
                    "Issue": "Invalid Time Range",
                    "Detail": (
                        "Check out must be later than Check in."
                    ),
                })
                continue
            downtime_hours = (end_datetime - start_datetime).total_seconds() / 3600
            downtime_type = checkin_row["Type Downtime"]
            if downtime_type == "":
                downtime_type = row["Type Downtime"]
            remarks = [value for value in [checkin_row["Remark"], row["Remark"]] if value]
            record_status = "Complete"
            # แจ้งเตือนกรณี Downtime เกิน 24 ชั่วโมง
            if downtime_hours > 24:
                record_status = "Check Duration"
                validation_rows.append({
                    "Source Row": row["Source_Row"],
                    "Machine Name": machine,
                    "Issue": "Long Downtime",
                    "Detail": (
                        f"Downtime is {downtime_hours:.2f} hr. "
                        "Please verify."
                    ),
                })
            downtime_rows.append({
                "Machine Name": machine,
                "EN": checkin_row["EN"],
                "Downtime Type": downtime_type,
                "Start_DateTime": start_datetime,
                "End_DateTime": end_datetime,
                "Calculated_Downtime_Hours": round(
                    downtime_hours,
                    2,
                ),
                "Production Date": get_production_date(
                    start_datetime
                ),
                "Shift": get_shift(
                    start_datetime
                ),
                "Remark": " | ".join(remarks),
                "Status": record_status,
                "Check In Row": checkin_row[
                    "Source_Row"
                ],
                "Check Out Row": row[
                    "Source_Row"
                ],
            })
    # ========================================================
    # REMAINING CHECK IN WITHOUT CHECK OUT
    # ========================================================
    for machine, checkin_row in active_checkins.items():
        start_datetime = checkin_row["Timestamp"]
        validation_rows.append({
            "Source Row": checkin_row["Source_Row"],
            "Machine Name": machine,
            "Issue": "Waiting Check out",
            "Detail": (
                "Check in has not been followed by Check out."
            ),
        })
        downtime_rows.append({
            "Machine Name": machine,
            "EN": checkin_row["EN"],
            "Downtime Type": checkin_row[
                "Type Downtime"
            ],
            "Start_DateTime": start_datetime,
            "End_DateTime": pd.NaT,
            "Calculated_Downtime_Hours": pd.NA,
            "Production Date": get_production_date(
                start_datetime
            ),
            "Shift": get_shift(
                start_datetime
            ),
            "Remark": checkin_row["Remark"],
            "Status": "Waiting Check out",
            "Check In Row": checkin_row[
                "Source_Row"
            ],
            "Check Out Row": pd.NA,
        })
    downtime_df = pd.DataFrame(downtime_rows)
    validation_df = pd.DataFrame(validation_rows)
    if not downtime_df.empty:
        downtime_df = downtime_df.sort_values(
            by=[
                "Production Date",
                "Machine Name",
                "Start_DateTime",
            ]
        ).reset_index(drop=True)
    if not validation_df.empty:
        validation_df = validation_df.sort_values(by="Source Row").reset_index(drop=True)
    return downtime_df, validation_df
# ============================================================
# MAIN READ FUNCTION
# ============================================================
def read_raw_downtime_sheet() -> pd.DataFrame:
    raw_df = download_raw_sheet()
    downtime_df, validation_df = pair_checkin_checkout(raw_df)
    if not validation_df.empty:
        print("\nDowntime validation warning:")
        print(validation_df.to_string(index=False))
    return downtime_df
# ============================================================
# YESTERDAY RESULT
# ============================================================
def get_downtime_yesterday():
    df = read_raw_downtime_sheet()
    target_date = date.today() - timedelta(days=1)

    if df.empty:
        result = {
            machine: 0.0
            for machine in MACHINES
        }
        print("Target Date:", target_date)
        print("Downtime Result:", result)
        return result, target_date

    completed_df = df[df["Status"].isin(["Complete", "Check Duration"])].copy()

    yesterday_df = completed_df[completed_df["Production Date"] == target_date].copy()
    result = {}
    for machine in MACHINES:
        machine_df = yesterday_df[yesterday_df["Machine Name"] == machine]
        downtime = calculate_unique_downtime_hours(machine_df)
        result[machine] = round(
            downtime,
            2,
        )
    print()
    print("Target Date:", target_date)
    print("Downtime Result:")
    for machine, downtime in result.items():
        print(f"{machine}: {downtime:.2f} hr")
    return result, target_date

# # ============================================================
# # TEST
# # ============================================================
# if __name__ == "__main__":
#     downtime_result, production_date = (get_downtime_yesterday())