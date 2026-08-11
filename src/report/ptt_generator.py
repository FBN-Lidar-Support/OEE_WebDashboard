import os
from shutil import copy2
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor

class PowerPointExporter:
    def __init__(self):
        self.template = r"C:\Projects\oee-dashboard\assets\template\OEE_Template.pptx"
        self.output_dir = r"C:\Projects\oee-dashboard\output\presentation"
        os.makedirs(self.output_dir, exist_ok=True)
    # ==========================================================
    # Replace Text
    # ==========================================================
    def _replace_text(self, prs, placeholder, value):
        value = str(value)
        for slide in prs.slides:
            for shape in slide.shapes:
                if not hasattr(shape, "text_frame"):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, value)
    # ==========================================================
    # Find Chart
    # ==========================================================
    def _find_chart(self, prs, chart_name):
        for slide in prs.slides:
            for shape in slide.shapes:
                if not shape.has_chart:
                    continue
                if shape.name == chart_name:
                    return shape.chart
        return None
    # ==========================================================
    # OEE Column Chart
    # ==========================================================
    def _update_oee_chart(self, prs, report_data):
        chart = self._find_chart(prs, "OEE_COMPARE")
        if chart is None:
            print("Chart OEE_COMPARE not found")
            return
        chart_data = CategoryChartData()
        chart_data.categories = ("AB2B", "AA", "IEOL_SHORT","IEOL_LONG")
        chart_data.add_series(
            "Actual",
            (
                self._to_float(report_data["AB2B"]["OEE"]),
                self._to_float(report_data["AA"]["OEE"]),
                self._to_float(report_data["IEOL_SHORT"]["OEE"]),
                self._to_float(report_data["IEOL_LONG"]["OEE"])
            )
        )
        chart_data.add_series(
            "Target",
            (
                float(report_data["target_oee"]),
                float(report_data["target_oee"]),
                float(report_data["target_oee"])
            )
        )
        chart.replace_data(chart_data)
        
    def _to_float(self, value):
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace("%", "").replace(",", "").strip())
        
    def _find_shape(self, prs, shape_name):
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.name == shape_name:
                    return shape
        return None
    def _update_status_shape(self, prs, shape_name, status):
        shape = self._find_shape(prs, shape_name)
        if shape is None:
            return
        if shape_name.split("_", 1)[-1] == "DT_STATUS":
            color = RGBColor(0, 176, 80)
        else:
            status = str(status).upper()
            if status == "ACHIEVED":
                color = RGBColor(0, 176, 80)      # Green
            elif status == "BELOW TARGET":
                color = RGBColor(255, 192, 0)     # Yellow
            else:
                color = RGBColor(180, 180, 180)   # Gray
        
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
    
    # ==========================================================
    # Downtime Pie Chart
    # ==========================================================
    def _update_pie_chart(self, prs, chart_name, downtime_type):
        PLANNED_TIME = 21
        chart = self._find_chart(prs, chart_name)
        if chart is None:
            print(f"{chart_name} not found")
            return
        chart_data = CategoryChartData()
        # =====================================================
        # No Downtime
        # =====================================================
        if len(downtime_type) == 0:
            chart_data.categories = [
                f"Production Time ({PLANNED_TIME:.1f} hr)"]
            chart_data.add_series("Hour", (PLANNED_TIME,))
        # =====================================================
        # Normal Downtime
        # =====================================================
        else:
            downtime_type = dict(sorted(downtime_type.items(), key=lambda x: x[1], reverse=True))
            total_dt = round(sum(downtime_type.values()), 2)
            running_time = max(PLANNED_TIME - total_dt, 0)
            chart_dict = downtime_type.copy()
            if running_time > 0:
                chart_dict["Production Time"] = round(running_time, 2)
            chart_data.categories = [
                f"{k} ({v:.1f} hr)"
                for k, v in chart_dict.items()
            ]
            chart_data.add_series("Hour", tuple(chart_dict.values()))
        chart.replace_data(chart_data)
        
        chart.replace_data(chart_data)
        # =====================================================
        # Set Production Time Slice = Green
        # =====================================================
        series = chart.series[0]
        categories = chart.plots[0].categories
        for idx, category in enumerate(categories):
            if "Production Time" in str(category):
                point = series.points[idx]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = RGBColor(0, 176, 80)
                break
        # =====================================================
        # Green Pie when No Downtime
        # =====================================================
        if len(downtime_type) == 0:
            point = chart.series[0].points[0]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = RGBColor(0, 176, 80)
            
    # ==========================================================
    # Update All Charts
    # ==========================================================
    def _update_all_charts(self, prs, report_data):
        self._update_oee_chart(prs, report_data)
        self._update_pie_chart(prs, "PIE_AB2B", report_data["AB2B"]["DowntimeType"])
        self._update_pie_chart(prs, "PIE_AA", report_data["AA"]["DowntimeType"])
        self._update_pie_chart(prs, "PIE_IEOL_S", report_data["IEOL_SHORT"]["DowntimeType"])
        self._update_pie_chart(prs, "PIE_IEOL_L", report_data["IEOL_LONG"]["DowntimeType"])

    def export_text(self, report_data):
        report_date = report_data["date"]
        output_file = os.path.join(self.output_dir, f"daily_oee_{report_date}.pptx")
        # Copy template
        copy2(self.template, output_file)
        # Open copied template
        prs = Presentation(output_file)
        ####################################################
        # Summary Page
        ####################################################
        self._replace_text(prs, "{{REPORT_DATE}}",      report_data["date"])
        self._replace_text(prs, "{{REPORT_PERIOD}}",    report_data["period"])
        self._replace_text(prs, "{{OEE_TARGET}}",       report_data["target_oee"])
        self._replace_text(prs, "{{ACTION_SUMMARY}}",   report_data["action"])
        self._replace_text(prs, "{{OVERALL_SUMMARY}}",  report_data["summary"])
        ####################################################
        # AB2B
        ####################################################
        self._replace_text(prs, "{{AB2B_TARGET}}",      report_data["AB2B"]["target"]["oee"])
        self._replace_text(prs, "{{AB2B_T_A}}",         report_data["AB2B"]["target"]["availability"])
        self._replace_text(prs, "{{AB2B_T_P}}",         report_data["AB2B"]["target"]["performance"])
        self._replace_text(prs, "{{AB2B_T_Q}}",         report_data["AB2B"]["target"]["quality"])
        self._replace_text(prs, "{{AB2B_OEE}}",         report_data["AB2B"]["OEE"])
        self._replace_text(prs, "{{AB2B_A}}",           report_data["AB2B"]["Availability"])
        self._replace_text(prs, "{{AB2B_P}}",           report_data["AB2B"]["Performance"])
        self._replace_text(prs, "{{AB2B_Q}}",           report_data["AB2B"]["Quality"])
        self._replace_text(prs, "{{AB2B_DT}}",          report_data["AB2B"]["Downtime"])
        self._replace_text(prs, "{{AB2B_STATUS}}",      report_data["AB2B"]["Status"])
        self._replace_text(prs, "{{AB2B_FOCUS}}",       report_data["AB2B"]["Focus"])
        self._replace_text(prs, "{{AB2B_ACTION}}",      report_data["AB2B"]["Action"])
        self._replace_text(prs, "{{AB2B_T_OUT}}",       report_data["AB2B"]["detail"]["output_last_opn"])
        self._replace_text(prs, "{{AB2B_T_IN}}",        report_data["AB2B"]["detail"]["input_first_opn"])
        ####################################################
        # AA
        ####################################################
        self._replace_text(prs, "{{AA_TARGET}}",        report_data["AA"]["target"]["oee"])
        self._replace_text(prs, "{{AA_T_A}}",           report_data["AA"]["target"]["availability"])
        self._replace_text(prs, "{{AA_T_P}}",           report_data["AA"]["target"]["performance"])
        self._replace_text(prs, "{{AA_T_Q}}",           report_data["AA"]["target"]["quality"])
        self._replace_text(prs, "{{AA_OEE}}",           report_data["AA"]["OEE"])
        self._replace_text(prs, "{{AA_A}}",             report_data["AA"]["Availability"])
        self._replace_text(prs, "{{AA_P}}",             report_data["AA"]["Performance"])
        self._replace_text(prs, "{{AA_Q}}",             report_data["AA"]["Quality"])
        self._replace_text(prs, "{{AA_DT}}",            report_data["AA"]["Downtime"])
        self._replace_text(prs, "{{AA_STATUS}}",        report_data["AA"]["Status"])
        self._replace_text(prs, "{{AA_FOCUS}}",         report_data["AA"]["Focus"])
        self._replace_text(prs, "{{AA_ACTION}}",        report_data["AA"]["Action"])
        self._replace_text(prs, "{{AA_FAS_T_OUT}}",     report_data["AA"]["detail"]["output_last_opn"]["FAS_SAS"])
        self._replace_text(prs, "{{AA_FAS_T_IN}}",      report_data["AA"]["detail"]["input_first_opn"]["FAS_SAS"])
        self._replace_text(prs, "{{AA_TP_T_OUT}}",      report_data["AA"]["detail"]["output_last_opn"]["TP"])
        self._replace_text(prs, "{{AA_TP_T_IN}}",       report_data["AA"]["detail"]["input_first_opn"]["TP"])
        ####################################################
        # IEOL SHORT
        ####################################################
        self._replace_text(prs, "{{IEOL_S_TARGET}}",    report_data["IEOL_SHORT"]["target"]["oee"])
        self._replace_text(prs, "{{IEOL_S_T_A}}",       report_data["IEOL_SHORT"]["target"]["availability"])
        self._replace_text(prs, "{{IEOL_S_T_P}}",       report_data["IEOL_SHORT"]["target"]["performance"])
        self._replace_text(prs, "{{IEOL_S_T_Q}}",       report_data["IEOL_SHORT"]["target"]["quality"])
        self._replace_text(prs, "{{IEOL_S_OEE}}",       report_data["IEOL_SHORT"]["OEE"])
        self._replace_text(prs, "{{IEOL_S_A}}",         report_data["IEOL_SHORT"]["Availability"])
        self._replace_text(prs, "{{IEOL_S_P}}",         report_data["IEOL_SHORT"]["Performance"])
        self._replace_text(prs, "{{IEOL_S_Q}}",         report_data["IEOL_SHORT"]["Quality"])
        self._replace_text(prs, "{{IEOL_S_DT}}",        report_data["IEOL_SHORT"]["Downtime"])
        self._replace_text(prs, "{{IEOL_S_STATUS}}",    report_data["IEOL_SHORT"]["Status"])
        self._replace_text(prs, "{{IEOL_S_FOCUS}}",     report_data["IEOL_SHORT"]["Focus"])
        self._replace_text(prs, "{{IEOL_S_ACTION}}",    report_data["IEOL_SHORT"]["Action"])
        self._replace_text(prs, "{{IEOL_S_T_OUT}}",     report_data["IEOL_SHORT"]["detail"]["output_last_opn"])
        self._replace_text(prs, "{{IEOL_S_T_IN}}",      report_data["IEOL_SHORT"]["detail"]["input_first_opn"])
        ####################################################
        # IEOL LONG
        ####################################################
        self._replace_text(prs, "{{IEOL_L_TARGET}}",    report_data["IEOL_LONG"]["target"]["oee"])
        self._replace_text(prs, "{{IEOL_L_T_A}}",       report_data["IEOL_LONG"]["target"]["availability"])
        self._replace_text(prs, "{{IEOL_L_T_P}}",       report_data["IEOL_LONG"]["target"]["performance"])
        self._replace_text(prs, "{{IEOL_L_T_Q}}",       report_data["IEOL_LONG"]["target"]["quality"])
        self._replace_text(prs, "{{IEOL_L_OEE}}",       report_data["IEOL_LONG"]["OEE"])
        self._replace_text(prs, "{{IEOL_L_A}}",         report_data["IEOL_LONG"]["Availability"])
        self._replace_text(prs, "{{IEOL_L_P}}",         report_data["IEOL_LONG"]["Performance"])
        self._replace_text(prs, "{{IEOL_L_Q}}",         report_data["IEOL_LONG"]["Quality"])
        self._replace_text(prs, "{{IEOL_L_DT}}",        report_data["IEOL_LONG"]["Downtime"])
        self._replace_text(prs, "{{IEOL_L_STATUS}}",    report_data["IEOL_LONG"]["Status"])
        self._replace_text(prs, "{{IEOL_L_FOCUS}}",     report_data["IEOL_LONG"]["Focus"])
        self._replace_text(prs, "{{IEOL_L_ACTION}}",    report_data["IEOL_LONG"]["Action"])
        self._replace_text(prs, "{{IEOL_L_T_OUT}}",     report_data["IEOL_LONG"]["detail"]["output_last_opn"])
        self._replace_text(prs, "{{IEOL_L_T_IN}}",      report_data["IEOL_LONG"]["detail"]["input_first_opn"])
        ####################################################
        # RESULT COLOR
        ####################################################
        self._update_status_shape(prs, "AB2B_RESULT_BOX", report_data["AB2B"]["Status"])
        if not report_data["AB2B"]["DowntimeType"]:
            self._update_status_shape(prs, "AB2B_DT_STATUS", report_data["AB2B"]["DowntimeType"])
            
        self._update_status_shape(prs, "AA_RESULT_BOX", report_data["AA"]["Status"])
        if not report_data["AA"]["DowntimeType"]:
            self._update_status_shape(prs, "AA_DT_STATUS", report_data["AA"]["DowntimeType"])
            
        self._update_status_shape(prs, "IEOL_RESULT_BOX", report_data["IEOL_SHORT"]["Status"])
        if not report_data["IEOL_SHORT"]["DowntimeType"]:
            self._update_status_shape(prs, "IEOL_DT_STATUS", report_data["IEOL_SHORT"]["DowntimeType"])

        self._update_status_shape(prs, "IEOL_RESULT_BOX", report_data["IEOL_LONG"]["Status"])
        if not report_data["IEOL_LONG"]["DowntimeType"]:
            self._update_status_shape(prs, "IEOL_DT_STATUS", report_data["IEOL_LONG"]["DowntimeType"])
        ####################################################
        # Charts
        ####################################################
        self._update_all_charts(prs, report_data)
        ####################################################
        prs.save(output_file)
        print(f"PPT Saved : {output_file}")
        return output_file
    

# report_data = {
#     "date": "2026-07-30",
#     "period": "[NIGHT Shift] 19:00 - 07:00\n[DAY Shift] 07:00 - 19:00",
#     "target": 85,
#     "summary": """Overall OEE was 82.6%.
# 2 of 3 machines were below target.
# Performance Loss remains the largest contributor.
# IEOL contributed the highest downtime.""",
#     "action": """1. Reduce IEOL downtime
# 2. Improve AA performance
# 3. Maintain AB2B stability""",
#     "AB2B": {
#         "OEE": 91.2,
#         "Availability": 95.4,
#         "Performance": 93.6,
#         "Quality": 99.5,
#         "Downtime": "0.75 hrs.",
#         "Target_OEE": 85,
#         "Status": "ACHIEVED",
#         "Focus": "Maintain current operating condition.",
#         "Action": "Continue monitoring material supply.",
#         "DowntimeType":{
#             "Material":1.8,
#             "Setup":0.7,
#             "Others":0.2
#         }
#     },
#     "AA":{
#         "OEE":82.4,
#         "Availability":87.5,
#         "Performance":84.3,
#         "Quality":98.9,
#         "Downtime":"1.85 hrs.",
#         "Target_OEE":85,
#         "Status":"ACHIEVED",
#         "Focus":"Improve cycle time.",
#         "Action":"Review calibration process.",
#         "DowntimeType":{
#             "Calibration":2.2,
#             "Setup":1.1,
#             "Material":0.4
#         }
#     },
#     "iEOL":{
#         "OEE":74.8,
#         "Availability":71.2,
#         "Performance":82.5,
#         "Quality":99.4,
#         "Downtime":"3.50 hrs.",
#         "Target_OEE":85,
#         "Status":"BELOW TARGET",
#         "Focus":"Reduce software downtime.",
#         "Action":"Maintenance root cause analysis.",
#         "DowntimeType":{
#             "Software":4.5,
#             "Network":1.4,
#             "Fixture":0.8
#         }
#     }
# }
# ppt = PowerPointExporter()
# ppt.export_text(report_data)