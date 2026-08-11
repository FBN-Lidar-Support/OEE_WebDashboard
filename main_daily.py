from src.etl.query_downtime import get_downtime_yesterday
from src.etl.query_yield import get_yield_yesterday
from src.calculation.oee_cal import calculate_oee
from src.analytics.smart_insight import generate_daily_insight
from src.report.excel_exporter import save_daily_excel
from src.report.ptt_generator import PowerPointExporter

def main():
    # 1. ดึงข้อมูล Downtime
    print("="*20, " downtime_data ", "="*20)
    (downtime_data, downtime_type, downtime_df, production_date) = get_downtime_yesterday()
    print("Production Date:\t", production_date)
    print("Downtime")
    for machine, hour in downtime_data.items():
        print(f"{machine:6s}"f" : {hour:.2f} hr")
    print()
    print("Downtime Type")
    for machine, value in downtime_type.items():
        print(machine)
        print(value)
        print()

    # 2. ดึงข้อมูล Yield
    print("="*20, " Yield_data ", "="*20)
    yield_data = get_yield_yesterday()
    for row in yield_data.items():
        print(row)
    
    # 3. คำนวณ OEE
    print("="*20, " oee_result ", "="*20)
    oee_result = calculate_oee(
        downtime_data=downtime_data,
        yield_data=yield_data
    )
    for row in oee_result.items():
        print(row)
        
    # 4. สร้าง Insight
    print("="*20, " insights ", "="*20)
    insights = generate_daily_insight(
        oee_result=oee_result,
        downtime_data=downtime_data,
        production_date=production_date
    )
    for key, value in insights.items():
        print("-"*5 , f" {key} ", "-"*5)
        for key, value in value.items():
            print(key)
            print(value)

    # 5. Save Excel history ไว้ในเครื่อง
    # print("="*20, " save_daily_excel ", "="*20)
    # excel_path = save_daily_excel(
    #     production_date=production_date,
    #     oee_result=oee_result,
    #     downtime_data=downtime_data,
    #     insights=insights
    # )
    # print("Excel saved:", excel_path)
    
    # 6. crate PPT report
    print("="*20, " PTT generate ", "="*20)
    report_data = {
        "date": insights["overall"]["production_date"],
        "period": "[NIGHT Shift] 19:00 - 07:00\n[DAY Shift] 07:00 - 19:00",
        "summary": "\n".join(insights["overall"]["summary"][1:]),
        "action": "\n".join(insights["overall"]["action"]),
        "target_oee": "80"
    }
    for key, value in insights.items():
        if key == "machines":
            for MC_NAME, row  in value.items():
                report_data.update({
                    MC_NAME: {
                        "OEE": row["oee"],
                        "Availability": row["availability"],
                        "Performance": row["performance"],
                        "Quality": row["quality"],
                        "Downtime": row["downtime"] + " hrs.",
                        "target": row["target"],
                        "Status": row["OEE_status"],
                        "Focus": "\n".join(row["focus"]),
                        "Action": "\n".join(row["action"]),
                        "detail": row["detail"],
                        "DowntimeType": downtime_type.get(MC_NAME, {})
                    }
                })
    ppt = PowerPointExporter()
    ppt.export_text(report_data)
    # for row in report_data.items():
    #     print(row)
        
    print("Daily OEE Report Completed")
    
if __name__ == "__main__":
    main()