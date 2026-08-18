# ==========================================================
# Helper
# ==========================================================
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
    availability_loss = average(100 - safe_number(machine["availability"]) for machine in oee_result.values())
    performance_loss = average(100 - safe_number(machine["performance"]) for machine in oee_result.values())
    quality_loss = average(100 - safe_number(machine["quality"]) for machine in oee_result.values())
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
    if overall_oee >= overall_target:
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
    ####################################################
    # Focus
    ####################################################
    focus = []
    if top_dt_machine and top_dt > 0:
        focus.append(f"Reduce downtime on {top_dt_machine}")
    if main_loss:
        if main_loss["category"] == "Availability":
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
    if top_dt_machine:
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
def get_machine_main_loss(machine):
    losses = {
        "Availability": max(100 - safe_number(machine["availability"]), 0),
        "Performance": max(100 - safe_number(machine["performance"]), 0),
        "Quality": max(100 - safe_number(machine["quality"]), 0)
    }
    category = max(losses, key=losses.get)
    return (category, round(losses[category], 2))
# ==========================================================
# Machine Summary
# ==========================================================
def generate_machine_summary(oee_result, downtime_data):
    machines = {}
    for name, item in oee_result.items():
        ####################################################
        # KPI
        ####################################################
        oee = safe_number(item["oee"])
        availability = safe_number(item["availability"])
        performance = safe_number(item["performance"])
        quality = safe_number(item["quality"])
        downtime = safe_number(downtime_data.get(name, item.get("downtime", 0)))
        ####################################################
        loss_name, loss_value = get_machine_main_loss(item)
        ####################################################
        summary = []
        focus = []
        action = []
        ####################################################
        # OEE
        ####################################################
        if oee >= item["target"]["oee"]:
            summary.append(f"OEE achieved {oee}% and met the target.")
        else:
            summary.append(f"OEE was {oee}%, below target.")
        ####################################################
        # Availability
        ####################################################
        if availability < item["target"]["availability"]:
            summary.append(f"Availability dropped to {availability}%.")
            focus.append("Reduce downtime")
            action.append("Review downtime records.")
        ####################################################
        # Performance
        ####################################################
        if performance < item["target"]["performance"]:
            summary.append(f"Performance was {performance}%.")
            focus.append("Improve cycle time")
            action.append("Review machine speed and operator loading.")
        ####################################################
        # Quality
        ####################################################
        if quality < item["target"]["quality"]:
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
        summary.append(f"Main loss : {loss_name} ({loss_value}%).")
        ####################################################
        # Recommendation
        ####################################################
        if loss_name == "Availability":
            action.append("Coordinate with Maintenance to improve equipment uptime.")
        elif loss_name == "Performance":
            action.append("Optimize machine cycle time and eliminate minor stops.")
        else:
            action.append("Perform root cause analysis for defects.")
        ####################################################
        machines[name] = {
            "oee": oee,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "downtime": hours_to_time(downtime),
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
            "detail": item["detail"]
        }
    return machines

# ==========================================================
# Daily Insight
# ==========================================================
def generate_daily_insight(oee_result, downtime_data, production_date):
    overall = generate_overall_summary(oee_result=oee_result, downtime_data=downtime_data, production_date=production_date)
    machines = generate_machine_summary(oee_result=oee_result, downtime_data=downtime_data)
    dashboard = {
        "overall": overall,
        "machines": machines
    }
    return dashboard