from pathlib import Path
import configparser
from src.etl.query_downtime import get_downtime_yesterday
from src.etl.query_yield import get_yield_yesterday
from src.calculation.oee_cal import calculate_oee
from src.analytics.smart_insight import generate_daily_insight
from src.storage.snapshot import save_daily_snapshot

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.ini"
config = configparser.ConfigParser()
# Explicit UTF-8: config.ini has Thai comments; the Windows default (cp874 on a
# Thai-locale server) cannot decode them.
if not config.read(CONFIG_PATH, encoding="utf-8-sig"):
    raise FileNotFoundError(f"Cannot read config: {CONFIG_PATH}")

def main():
    Machine_OPN = {
        "AB2B"          : config["AB2B"].get("OPN_LIST", {}).split(","),
        "AA_FAS_SAS"    : config["AA_FAS_SAS"].get("OPN_LIST", {}).split(","),
        "AA_TP"         : config["AA_TP"].get("OPN_LIST", {}).split(","),
        "IEOL_BRINGUP"  : config["IEOL_BRINGUP"].get("OPN_LIST", {}).split(","),
        "IEOL_S"        : config["IEOL_SHORT"].get("OPN_LIST", {}).split(","),
        "IEOL_L"        : config["IEOL_LONG"].get("OPN_LIST", {}).split(","),
        # Same machines as IEOL_BRINGUP (different program); combined in oee_cal.
        "IEOL_CRS"      : config["IEOL_CRS"].get("OPN_LIST", {}).split(","),
    }

    # 1. ดึงข้อมูล Downtime
    print("=" * 20, " downtime_data ", "=" * 20)
    # Bad downtime rows are skipped (not fatal) and listed here per machine;
    # those machines are marked DATA INCOMPLETE in the OEE result.
    downtime_issues = {}
    downtime_data, downtime_type, downtime_df, production_date = get_downtime_yesterday(downtime_issues)
    for machine, messages in downtime_issues.items():
        for message in messages:
            print(f"WARNING skipped downtime row [{machine}]: {message}")
    print("Production Date:\t", production_date)
    # for machine, hour in downtime_data.items():
    #     print(f"{machine:6s} : {hour:.2f} hr")
    print("====================== Downtime Type ======================")
    for machine, value in downtime_type.items():
        print(machine)
        print(value)
    # print("====================== downtime df ======================")
    # print(downtime_df)

    # 2. ดึงข้อมูล Yield
    print("=" * 20, " Yield_data ", "=" * 20)
    yield_data = get_yield_yesterday(MC_DICT = Machine_OPN)
    for process, data in yield_data.items():
        print(f"\n=== {process} ===")
        print(f"Total Input: {data['input_first_opn']}")
        print(f"Total Output: {data['total_last_opn']}")
        print(f"Total Pass: {data['pass_last_opn']}")
        print(f"Duration: {data['duration_hr']} hr")
        for machine, values in data["machines"].items():
            print(f"  {machine}: {values}")

    # 3. คำนวณ OEE
    print("=" * 20, " oee_result ", "=" * 20)
    oee_data = calculate_oee(
        downtime_data=downtime_data,
        yield_data=yield_data,
        downtime_type_data=downtime_type,
        downtime_issues=downtime_issues
    )
    for machine, row in oee_data.items():
        detail = row["detail"]
        bar = row["time_bar"]
        print(f"\n=== {machine} ===")
        print(
            f"OEE={row['oee']}% | "
            f"A={row['availability']}% | "
            f"P={row['performance']}% | "
            f"Q={row['quality']}% | "
            f"Quality OK={row['data_quality_ok']}"
        )
        print(
            f"Planned={detail['planned_time']:.3f} hr | "
            f"Operating={detail['operating_time']:.3f} hr | "
            f"Active={detail['active_time']:.3f} hr | "
            f"Unknown={detail['unknown_time']:.3f} hr | "
            f"Downtime={row['downtime']:.3f} hr | "
            f"Ideal={detail['ideal_time']:.3f} hr"
        )
        print("Downtime Types:")
        for name, hours in bar["adjusted_downtime_by_type"].items():
            print(f"  {name}: {hours:.3f} hr")
        if row["data_quality_issues"]:
            print(f"Data Quality Issues: {row['data_quality_issues']}")

    # 4. สร้าง Smart Insight / Dashboard Data
    print("=" * 20, " insights ", "=" * 20)
    insights = generate_daily_insight(
        oee_result=oee_data,
        downtime_data=downtime_data,
        downtime_type=downtime_type,
        production_date=production_date
    )
    for key, value in insights.items():
        print("-" * 5, f" {key} ", "-" * 5)
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                print(sub_key)
                print(sub_value)
        else:
            print(value)

    # 5. บันทึก Daily JSON Snapshot
    print("=" * 20, " Save Snapshot ", "=" * 20)
    snapshot_path = save_daily_snapshot(
        insights,
        config_path=CONFIG_PATH,
        status="FINAL"
    )
    print(f"Snapshot saved successfully: {snapshot_path}")
if __name__ == "__main__":
    main()