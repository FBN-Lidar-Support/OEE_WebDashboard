from src.etl.query_downtime import get_downtime_yesterday
from src.etl.query_yield import get_yield_yesterday
from src.calculation.oee_cal import calculate_oee
from src.analytics.smart_insight import generate_daily_insight
from src.report.excel_exporter import save_daily_excel
from src.report.google_slide_updater import update_daily_google_slide
from src.report.daily_ppt_exporter import save_daily_presentation

def main():
    # 1. ดึงข้อมูล
    print("="*20, " downtime_data ", "="*20)
    downtime_data, production_date = get_downtime_yesterday()
    print("Production Date:\t", production_date)
    print(downtime_data)
    
    print("="*20, " yield_data ", "="*20)
    yield_data = get_yield_yesterday()
    for row in yield_data.items():
        print(row)
    
    # 2. คำนวณ OEE
    print("="*20, " oee_result ", "="*20)
    oee_result = calculate_oee(
        downtime_data=downtime_data,
        yield_data=yield_data
    )
    for row in oee_result:
        print(row)
    quit()
    # 3. สร้าง Insight
    print("="*20, " insights ", "="*20)
    insights = generate_daily_insight(
        oee_result=oee_result,
        downtime_data=downtime_data,
        production_date=production_date
    )
    for row in insights:
        print(row)
    
    # 4. Save Excel history ไว้ในเครื่อง
    print("="*20, " save_daily_excel ", "="*20)
    excel_path = save_daily_excel(
        production_date=production_date,
        oee_result=oee_result,
        downtime_data=downtime_data,
        insights=insights
    )
    
    # # 5. Update Google Slides
    # update_daily_google_slide(
    #     production_date=production_date,
    #     oee_result=oee_result,
    #     insights=insights,
    #     excel_path=excel_path
    # )
    
    print("Daily OEE Report Completed")
    print("Excel saved:", excel_path)
    
if __name__ == "__main__":
    main()