import os
import pandas as pd
def save_daily_excel(
    production_date,
    oee_result,
    downtime_data,
    insights
):
    output_dir = "output/excel_history"
    os.makedirs(output_dir, exist_ok=True)
    date_text = str(production_date).replace("-", "")
    file_path = os.path.join(
        output_dir,
        f"daily_oee_{date_text}.xlsx"
    )
    # Sheet 1: OEE Summary
    df_oee = pd.DataFrame(oee_result)
    # Sheet 2: Downtime Summary
    downtime_rows = []
    for machine, downtime in downtime_data.items():
        downtime_rows.append({
            "machine": machine,
            "downtime_hr": round(downtime, 2)
        })
    df_downtime = pd.DataFrame(downtime_rows)
    # Sheet 3: Smart Insights
    df_insights = pd.DataFrame(insights)
    # Sheet 4: Report Info
    df_info = pd.DataFrame([
        {
            "report_type": "Daily OEE Report",
            "production_date": str(production_date),
            "generated_by": "Python OEE Reporting Platform"
        }
    ])
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df_info.to_excel(
            writer,
            sheet_name="Report Info",
            index=False
        )
        df_oee.to_excel(
            writer,
            sheet_name="OEE Summary",
            index=False
        )
        df_downtime.to_excel(
            writer,
            sheet_name="Downtime Summary",
            index=False
        )
        df_insights.to_excel(
            writer,
            sheet_name="Smart Insights",
            index=False
        )
    print(f"Excel report saved: {file_path}")
    return file_path