from src.calculation.oee_cal import _machine_name
# ==========================================================
# Helper
# ==========================================================
def normalize_machine_keys(data):
    """ORA#865871 AB2B01 -> AB2B01 ให้ตรงกับ oee_result"""
    out = {}
    for name, value in (data or {}).items():
        key = _machine_name(name)
        if key in out:
            raise ValueError(f"Duplicate machine after normalize: {key}")
        out[key] = value
    return out
def safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default
def hours_to_time(hours):
    try:
        total_minutes = round(float(hours) * 60)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}:{m:02d}"
    except Exception:
        return "0:00"
# Unknown time = planned time with no FITS run and no downtime keyed in
# (operator forgot to record, material shortage, waiting ...). It is an
# Availability loss, so the insight says so instead of just "reduce downtime".
UNKNOWN_SHARE_NOTICE = 0.05   # mention when >= 5% of planned time
UNKNOWN_ACTION = (
    "Ask operators to key in downtime (e.g. material shortage, waiting for parts) "
    "for the unexplained time."
)
def get_unknown_time(item):
    """(unknown_hr, planned_hr, share_of_planned) of one machine result."""
    detail = item.get("detail") or {}
    unknown = safe_number(detail.get("unknown_time"))
    planned = safe_number(detail.get("planned_time"))
    return unknown, planned, (unknown / planned if planned > 0 else 0.0)
def average(values):
    values = [safe_number(v) for v in values]
    if not values:
        return 0
    return round(sum(values) / len(values), 2)
# ==========================================================
# Overall KPI
# ==========================================================
def get_overall_oee(oee_result):
    return average(machine["oee"] for machine in oee_result.values())
def get_total_downtime(downtime_data):
    return round(sum(safe_number(v) for v in downtime_data.values()), 2)
def get_best_machine(oee_result):
    if not oee_result:
        return None
    return max(oee_result.items(), key=lambda item: safe_number(item[1]["oee"]))[0]
def get_worst_machine(oee_result):
    if not oee_result:
        return None
    return min(oee_result.items(), key=lambda item: safe_number(item[1]["oee"]))[0]
def get_top_downtime(downtime_data):
    if not downtime_data:
        return None, 0
    machine = max(downtime_data, key=downtime_data.get)
    return (machine, round(safe_number(downtime_data[machine]), 2))
# ==========================================================
# Loss
# ==========================================================
def get_main_loss(oee_result):
    if not oee_result:
        return None
    # A loss is never negative per machine (Performance > 100% must not
    # cancel out other machines' losses).
    availability_loss = average(max(100 - safe_number(machine["availability"]), 0) for machine in oee_result.values())
    performance_loss = average(max(100 - safe_number(machine["performance"]), 0) for machine in oee_result.values())
    quality_loss = average(max(100 - safe_number(machine["quality"]), 0) for machine in oee_result.values())
    losses = {
        "Availability": availability_loss,
        "Performance": performance_loss,
        "Quality": quality_loss
    }
    category = max(losses, key=losses.get)
    return {
        "category": category,
        "value": round(losses[category], 2)
    }
# ==========================================================
# Overall Summary
# ==========================================================
def generate_overall_summary(oee_result, downtime_data, production_date):
    overall_oee = get_overall_oee(oee_result)
    overall_target = average(machine["target"]["oee"] for machine in oee_result.values())
    best_machine = get_best_machine(oee_result)
    worst_machine = get_worst_machine(oee_result)
    top_dt_machine, top_dt = get_top_downtime(downtime_data)
    main_loss = get_main_loss(oee_result)
    ####################################################
    # Below Target
    ####################################################
    below_target = sum(1 for machine in oee_result.values() if safe_number(machine["oee"]) < safe_number(machine["target"]["oee"]))
    ####################################################
    # Summary
    ####################################################
    summary = []
    if not oee_result:
        summary.append("Overall OEE could not be calculated (no machine with complete data).")
    elif overall_oee >= overall_target:
        summary.append(f"Overall OEE achieved {overall_oee}% (Target {overall_target}%).")
    else:
        summary.append(f"Overall OEE was {overall_oee}% ({round(overall_target-overall_oee,2)}% below target).")
    summary.append(f"{below_target} of {len(oee_result)} machines were below target.")
    if best_machine:
        summary.append(f"Best machine : {best_machine} ({oee_result[best_machine]['oee']}%).")
    if worst_machine:
        summary.append(f"Worst machine : {worst_machine} ({oee_result[worst_machine]['oee']}%).")
    if main_loss:
        summary.append(f"Main loss : {main_loss['category']} ({main_loss['value']}%).")
    if top_dt_machine:
        summary.append(f"Highest downtime : {top_dt_machine} ({hours_to_time(top_dt)}).")
    unknown_total = planned_total = 0.0
    unknown_machines = 0
    for item in oee_result.values():
        unknown, planned, share = get_unknown_time(item)
        unknown_total += unknown
        planned_total += planned
        if share >= UNKNOWN_SHARE_NOTICE:
            unknown_machines += 1
    unknown_share = unknown_total / planned_total if planned_total > 0 else 0.0
    unknown_notable = unknown_share >= UNKNOWN_SHARE_NOTICE
    if unknown_notable:
        summary.append(
            f"Unexplained time totaled {hours_to_time(unknown_total)} "
            f"({round(unknown_share * 100, 1)}% of planned time) on {unknown_machines} machines."
        )
    ####################################################
    # Focus
    ####################################################
    focus = []
    if top_dt_machine and top_dt > 0:
        focus.append(f"Reduce downtime on {top_dt_machine}")
    if unknown_notable:
        focus.append("Record reasons for unexplained time")
    if main_loss:
        if main_loss["category"] == "Availability":
            if not unknown_notable or top_dt > 0:
                focus.append("Improve machine uptime")
        elif main_loss["category"] == "Performance":
            focus.append("Improve machine cycle time")
        else:
            focus.append("Reduce defect rate")
    if worst_machine:
        focus.append(f"Recover OEE of {worst_machine}")
    ####################################################
    # Action
    ####################################################
    action = []
    if unknown_notable:
        action.append(UNKNOWN_ACTION)
    if top_dt_machine and top_dt > 0:
        action.append(f"Assign Maintenance to investigate {top_dt_machine}.")
    if worst_machine:
        action.append(f"Review OEE loss of {worst_machine}.")
    if main_loss:
        action.append(f"Prioritize {main_loss['category']} improvement.")
    ####################################################
    return {
        "production_date": production_date,
        "summary": list(dict.fromkeys(summary)),
        "focus": list(dict.fromkeys(focus)),
        "action": list(dict.fromkeys(action)),
        "best_machine": best_machine,
        "worst_machine": worst_machine
    }
# ==========================================================
# Machine Main Loss
# ==========================================================
def optional_number(value):
    """Return float, or None when the KPI could not be calculated."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
def get_machine_main_loss(machine):
    losses = {
        name: max(100 - value, 0)
        for name, value in (
            ("Availability", optional_number(machine["availability"])),
            ("Performance", optional_number(machine["performance"])),
            ("Quality", optional_number(machine["quality"]))
        )
        if value is not None
    }
    if not losses:
        return (None, None)
    category = max(losses, key=losses.get)
    return (category, round(losses[category], 2))
# ==========================================================
# Machine Summary
# ==========================================================
def generate_machine_summary(oee_result: dict, downtime_data, downtime_type: dict):
    machines = {}
    for name, item in oee_result.items():
        ####################################################
        # KPI
        ####################################################
        # Keep None (not 0) for KPIs that cannot be calculated,
        # so the dashboard shows "-" instead of a fake 0%.
        oee = optional_number(item["oee"])
        availability = optional_number(item["availability"])
        performance = optional_number(item["performance"])
        quality = optional_number(item["quality"])
        downtime = safe_number(item.get("downtime", 0))  # ค่าที่ปรับด้วย FITS แล้ว ตรงกับ A
        unknown, _planned, unknown_share = get_unknown_time(item)
        unknown_notable = unknown_share >= UNKNOWN_SHARE_NOTICE
        unknown_dominant = unknown_notable and unknown > downtime
        ####################################################
        loss_name, loss_value = get_machine_main_loss(item)
        ####################################################
        summary = []
        focus = []
        action = []
        ####################################################
        # OEE
        ####################################################
        if oee is None or not item.get("data_quality_ok", True):
            issues = ", ".join(item.get("data_quality_issues", []))
            summary.append(f"Data incomplete ({issues}).")
        elif oee >= item["target"]["oee"]:
            summary.append(f"OEE achieved {oee}% and met the target.")
        else:
            summary.append(f"OEE was {oee}%, below target.")
        ####################################################
        # Availability
        ####################################################
        if availability is not None and availability < item["target"]["availability"]:
            summary.append(f"Availability dropped to {availability}%.")
            if downtime > 0:
                focus.append("Reduce downtime")
                action.append("Review downtime records.")
            if unknown_notable:
                summary.append(
                    f"Unexplained time was {hours_to_time(unknown)} "
                    f"({round(unknown_share * 100, 1)}% of planned time): "
                    "no run recorded in FITS and no downtime keyed in."
                )
                focus.append("Record reasons for unexplained time")
                action.append(UNKNOWN_ACTION)
        ####################################################
        # Performance
        ####################################################
        if performance is None:
            summary.append("Performance could not be calculated.")
        elif performance > 100:
            summary.append(
                f"Performance was {performance}% (over 100%): the machine ran faster "
                "than the ideal speed set in config for its actual run time."
            )
            focus.append("Verify ideal speed")
            action.append(
                "Check IDEAL_SPEED in config and whether FITS DURATION covers the full run time."
            )
        elif performance < item["target"]["performance"]:
            summary.append(f"Performance was {performance}%.")
            focus.append("Improve cycle time")
            action.append("Review machine speed and operator loading.")
        ####################################################
        # Quality
        ####################################################
        if quality is None:
            summary.append("Quality could not be calculated.")
        elif quality < item["target"]["quality"]:
            summary.append(f"Quality was {quality}%.")
            focus.append("Reduce defects")
            action.append("Investigate NG trend.")
        ####################################################
        # Downtime
        ####################################################
        if downtime > 0:
            summary.append(f"Downtime totaled {hours_to_time(downtime)}.")
        else:
            summary.append("No downtime was recorded.")
        ####################################################
        # Main Loss
        ####################################################
        if loss_name:
            if loss_name == "Availability" and unknown_dominant:
                summary.append(f"Main loss : Availability ({loss_value}%), mostly unexplained time.")
            else:
                summary.append(f"Main loss : {loss_name} ({loss_value}%).")
        ####################################################
        # Recommendation
        ####################################################
        if loss_name == "Availability":
            # Maintenance helps only with recorded downtime; unexplained time
            # has no known cause yet.
            if not unknown_dominant:
                action.append("Coordinate with Maintenance to improve equipment uptime.")
        elif loss_name == "Performance":
            action.append("Optimize machine cycle time and eliminate minor stops.")
        elif loss_name == "Quality":
            action.append("Perform root cause analysis for defects.")
        ####################################################
        machines[name] = {
            "oee": oee,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "downtime": hours_to_time(downtime),
            "downtime_detail": downtime_type.get(name, {}),
            "target": item["target"],
            "OEE_status": item["oee_status"],
            "A_status": item["a_status"],
            "P_status": item["p_status"],
            "Q_status": item["q_status"],
            "main_loss": {
                "category": loss_name,
                "value": loss_value
            },
            "summary": list(dict.fromkeys(summary)),
            "focus": list(dict.fromkeys(focus)),
            "action": list(dict.fromkeys(action)),
            "detail": item["detail"],
            "time_bar": item["time_bar"],
            "data_quality_ok": item["data_quality_ok"],
            # Issue codes + exact downtime CSV rows that were skipped (file/row to fix).
            "data_quality_issues": item["data_quality_issues"] + item.get("downtime_skipped_rows", []),
        }
    return machines
# ==========================================================
# Daily Insight
# ==========================================================
def generate_daily_insight(oee_result, downtime_data, downtime_type, production_date):
    downtime_data = normalize_machine_keys(downtime_data)
    downtime_type = normalize_machine_keys(downtime_type)
    # นับ downtime เฉพาะเครื่องที่มี OEE (ลบบรรทัดนี้ถ้าอยากรวมสถานีอื่น เช่น TP01, Screwing)
    downtime_data = {k: v for k, v in downtime_data.items() if k in oee_result}
    # เครื่องที่ OEE คำนวณไม่ได้ (None) ไม่เอามาเฉลี่ย (ดูแก้ 3)
    valid = {k: v for k, v in oee_result.items() if v["oee"] is not None}
    overall = generate_overall_summary(oee_result=valid, downtime_data=downtime_data, production_date=production_date)
    overall["excluded_machines"] = sorted(set(oee_result) - set(valid))
    machines = generate_machine_summary(oee_result=oee_result, downtime_data=downtime_data, downtime_type=downtime_type)
    dashboard = {
        "overall": overall,
        "machines": machines
    }
    return dashboard