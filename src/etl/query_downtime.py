from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta, time as dt_time
from io import StringIO
import time
import pandas as pd
import requests

# ============================================================
# CONFIG
# ============================================================
SHEET_ID = "1GX-QmKKZivETF-5s77m0LNAfT0M8LxKm7i2nVqtxUY8"
RAW_GID = "126900875"
RAW_DATA_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"f"/export?format=csv&gid={RAW_GID}")
DAY_SHIFT_START = dt_time(7, 0)
NIGHT_SHIFT_START = dt_time(19, 0)

# ============================================================
# DOWNLOAD GOOGLE SHEET
# ============================================================
def download_raw_sheet():
    cache_url = (RAW_DATA_URL + "&t=" + str(int(time.time())))
    try:
        response = requests.get(cache_url,timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Download Google Sheet Failed : {e}")
    df = pd.read_csv(StringIO(response.text))
    df.columns = (df.columns.astype(str).str.strip())
    return df

# ============================================================
# NORMALIZE
# ============================================================
def normalize_check_status(value):
    if pd.isna(value):
        return None
    text = (str(value).lower().strip())
    text = " ".join(text.split())
    if text in ["check in", "checkin", "start"]:
        return "check in"
    if text in ["check out", "checkout", "end"]:
        return "check out"
    return None

# ============================================================
# PARSE TIMESTAMP
# ============================================================
def parse_timestamp(value):
    if pd.isna(value):
        return pd.NaT
    text = str(value).strip()
    formats = [
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S"
    ]
    for fmt in formats:
        try:
            return pd.to_datetime(text, format=fmt)
        except Exception:
            pass
    return pd.NaT

# ============================================================
# SHIFT
# ============================================================
def get_shift(timestamp):
    if DAY_SHIFT_START <= timestamp.time() < NIGHT_SHIFT_START:
        return "DAY"
    return "NIGHT"

# ============================================================
# PRODUCTION DATE
# ============================================================
def get_production_date(timestamp):
    if timestamp.time() < DAY_SHIFT_START:
        return (timestamp - timedelta(days=1)).date()
    return timestamp.date()

# ============================================================
# CLEAN DATAFRAME
# ============================================================
def clean_dataframe(raw_df):
    df = raw_df.copy()
    ########################################################
    df.columns = (df.columns.astype(str).str.strip())
    ########################################################
    df["Machine Name"] = (df["Machine Name"].astype(str).str.strip())
    ########################################################
    df["Type Downtime"] = (df["Type Downtime"].fillna("").astype(str).str.strip().replace(
            {
                "Other (Please Remark)": "Others",
                "Others (Please explain in remark)": "Others"
            }
        )
    )
    ########################################################
    df["Downtime Check in / Check out"] = (df["Downtime Check in / Check out"].apply(normalize_check_status))
    ########################################################
    df["Timestamp"] = (df["Timestamp"].apply(parse_timestamp))
    ########################################################
    df["Remark"] = (df["Remark"].fillna("").astype(str).str.strip())
    ########################################################
    df = df.dropna(subset=["Timestamp","Machine Name","Downtime Check in / Check out"])
    ########################################################
    df = (df.sort_values("Timestamp").reset_index(drop=True))
    return df

# ============================================================
# GET MACHINE LIST
# ============================================================
def get_machine_list(df):
    return sorted(df["Machine Name"].dropna().astype(str).str.strip().unique().tolist())

# ============================================================
# MERGE OVERLAP
# ============================================================
def merge_intervals(intervals):
    if len(intervals) == 0:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged

# ============================================================
# UNIQUE DOWNTIME
# ============================================================
def calculate_unique_downtime_hours(machine_df):
    intervals = []
    for _, row in machine_df.iterrows():
        intervals.append((row["Start_DateTime"], row["End_DateTime"]))
    merged = merge_intervals(intervals)
    total_hour = sum((end - start).total_seconds() / 3600 for start, end in merged)
    return round(total_hour, 2)

# ============================================================
# PAIR CHECK IN / CHECK OUT
# ============================================================
def pair_checkin_checkout(raw_df):
    df = clean_dataframe(raw_df)
    active = defaultdict(list)
    downtime_rows = []
    validation_rows = []
    ########################################################
    for idx, row in df.iterrows():
        machine = row["Machine Name"]
        dtype = row["Type Downtime"]
        action = row["Downtime Check in / Check out"]
        key = (machine, dtype)
        ####################################################
        # CHECK IN
        ####################################################
        if action == "check in":
            active[key].append(row)
            continue
        ####################################################
        # CHECK OUT
        ####################################################
        if action == "check out":
            ################################################
            if len(active[key]) == 0:
                validation_rows.append({
                    "Row": idx + 2,
                    "Machine Name": machine,
                    "Issue": "Missing Check in",
                    "Type": dtype
                })
                continue
            ################################################
            checkin = active[key].pop()
            ################################################
            start = checkin["Timestamp"]
            end = row["Timestamp"]
            ################################################
            if end <= start:
                validation_rows.append({
                    "Row": idx + 2,
                    "Machine Name": machine,
                    "Issue": "Invalid Time Range",
                    "Type": dtype
                })
                continue
            ################################################
            downtime_hour = round(
                (end - start).total_seconds() / 3600, 2)
            ################################################
            # Warning
            ################################################
            warning = ""
            if downtime_hour > 24:
                warning = "Long Downtime"
                validation_rows.append({
                    "Row": idx + 2,
                    "Machine Name": machine,
                    "Issue": warning,
                    "Type": dtype,
                    "Downtime(hr)": downtime_hour
                })
            ################################################
            downtime_rows.append({
                "Machine Name": machine,
                "Type Downtime": dtype,
                "Production Date": get_production_date(start),
                "Shift": get_shift(start),
                "Start_DateTime": start,
                "End_DateTime": end,
                "Downtime(hr)": downtime_hour,
                "Checkin EN": checkin["EN"],
                "Checkout EN": row["EN"],
                "Remark Start": checkin["Remark"],
                "Remark End": row["Remark"],
                "Warning": warning
            })
    ########################################################
    # Waiting Check out
    ########################################################
    for key, stack in active.items():
        machine, dtype = key
        while stack:
            checkin = stack.pop()
            validation_rows.append({
                "Row": "-",
                "Machine Name": machine,
                "Issue": "Waiting Check out",
                "Type": dtype,
                "Checkin Time": checkin["Timestamp"]
            })
    ########################################################
    downtime_df = pd.DataFrame(downtime_rows)
    validation_df = pd.DataFrame(validation_rows)
    return downtime_df, validation_df

# ============================================================
# DOWNTIME TYPE SUMMARY
# ============================================================
def summarize_downtime_type(downtime_df, machine, min_hour=0.083):
    machine_df = downtime_df[downtime_df["Machine Name"] == machine]
    if machine_df.empty:
        return {}
    summary = (machine_df.groupby("Type Downtime")["Downtime(hr)"].sum().sort_values(ascending=False))
    print(summary)
    result = {}
    other_hour = 0
    for dtype, hour in summary.items():
        if hour >= min_hour:
            result[dtype] = round(hour, 2)
        else:
            other_hour += hour
    if other_hour > 0:
        result["Others"] = round(other_hour, 2)
    return result
# ============================================================
# READ RAW SHEET
# ============================================================
def read_raw_downtime_sheet():
    raw_df = download_raw_sheet()
    downtime_df, validation_df = pair_checkin_checkout(raw_df)
    target_date = date.today() - timedelta(days=1)
    ####################################################
    # Filter เฉพาะ Production Date ที่จะทำ Report
    ####################################################
    downtime_df = downtime_df[downtime_df["Production Date"] == target_date].copy()
    ####################################################
    # Validation เฉพาะของวันนั้น
    ####################################################
    if not validation_df.empty:
        validation_df = validation_df[(validation_df.get("Checkin Time").dt.date.fillna(target_date) == target_date)]
        if not validation_df.empty:
            print("\nDowntime Validation")
            print(validation_df.to_string(index=False))
    return downtime_df

# ============================================================
# YESTERDAY DOWNTIME
# ============================================================
def get_downtime_yesterday():
    # Raw ทั้งหมด (ไม่กรองวันที่)
    raw_df = clean_dataframe(download_raw_sheet())
    # ใช้แค่ดึงชื่อเครื่อง
    # machines = get_machine_list(raw_df)
    machines = ["AB2B", "AA", "IEOL SHORT", "IEOL LONG"]
    # ข้อมูลเมื่อวาน
    df = read_raw_downtime_sheet()
    
    target_date = date.today() - timedelta(days=1)
    
    result = {}
    downtime_type = {}
    for machine in machines:
        machine_df = df[df["Machine Name"] == machine]
        result[machine] = calculate_unique_downtime_hours(machine_df)
        downtime_type[machine] = summarize_downtime_type(df, machine)
    return (result, downtime_type, df, target_date)
    
# ============================================================
# VALIDATION SUMMARY
# ============================================================
def print_validation_summary(validation_df):
    print()
    print("=" * 60)
    print("Validation Summary")
    print("=" * 60)
    if validation_df.empty:
        print("No Validation Issue.")
        return
    print(validation_df.groupby("Issue").size().to_string())
    print()
    print(validation_df.to_string(index=False))
# ============================================================
# DOWNTIME SUMMARY
# ============================================================
def print_downtime_summary(downtime_df):
    print()
    print("=" * 60)
    print("Downtime Summary")
    print("=" * 60)
    if downtime_df.empty:
        print("No Downtime Record")
        return
    summary = (downtime_df.groupby("Machine Name")["Downtime(hr)"].sum().round(2))
    print(summary)
    print()
    print("Total Downtime :",round(downtime_df["Downtime(hr)"].sum(), 2), "hr")
    print("Total Event :",len(downtime_df))
# ============================================================
# DEBUG
# ============================================================
def debug():
    raw_df = download_raw_sheet()
    downtime_df, validation_df = pair_checkin_checkout(raw_df)
    print_validation_summary(validation_df)
    print_downtime_summary(downtime_df)
    print()
    print("=" * 60)
    print("Downtime Data")
    print("=" * 60)
    print(downtime_df.to_string(index=False))
# ============================================================
# TEST
# ============================================================
# if __name__ == "__main__":
#     # debug()
#     # print()
#     (downtime_result, downtime_type, downtime_df, production_date) = get_downtime_yesterday()
#     print(downtime_result)
#     print("=" * 60)
#     print("Yesterday Result")
#     print("=" * 60)
#     print("Production Date :", production_date)
#     print()
#     print("Downtime")
#     for machine, hour in downtime_result.items():
#         print(f"{machine:6s}"f" : {hour:.2f} hr")
#     print()
#     print("Downtime Type")
#     for machine, value in downtime_type.items():
#         print(machine)
#         print(value)
#         print()