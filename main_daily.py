from pathlib import Path
from src.etl.query_downtime import get_downtime_yesterday
from src.etl.query_yield import get_yield_yesterday
from src.calculation.oee_cal import calculate_oee
from src.analytics.smart_insight import generate_daily_insight
from src.storage.snapshot import save_daily_snapshot

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.ini"
def main():
    # 1. ดึงข้อมูล Downtime
    print("=" * 20, " downtime_data ", "=" * 20)
    downtime_data, downtime_type, downtime_df, production_date = (
        get_downtime_yesterday()
    )
    print("Production Date:\t", production_date)
    for machine, hour in downtime_data.items():
        print(f"{machine:6s} : {hour:.2f} hr")
    print("====================== Downtime Type ======================")
    for machine, value in downtime_type.items():
        print(machine)
        print(value)
    print("====================== downtime df ======================")
    print(downtime_df)
    # 2. ดึงข้อมูล Yield
    print("=" * 20, " Yield_data ", "=" * 20)
    yield_data = get_yield_yesterday()
    for row in yield_data.items():
        print(row)
    # 3. คำนวณ OEE
    print("=" * 20, " oee_result ", "=" * 20)
    oee_result = calculate_oee(
        downtime_data=downtime_data,
        yield_data=yield_data
    )
    for row in oee_result.items():
        print(row)
    # 4. สร้าง Smart Insight / Dashboard Data
    print("=" * 20, " insights ", "=" * 20)
    insights = generate_daily_insight(
        oee_result=oee_result,
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