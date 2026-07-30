TARGET_OEE = 85
TARGET_AVAILABILITY = 85
TARGET_PERFORMANCE = 85
TARGET_QUALITY = 85

def safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default
def hours_to_time_format(hours):
    try:
        total_minutes = round(float(hours) * 60)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}:{m:02d}"
    except Exception:
        return "0:00"
def get_overall_oee(oee_result):
    if not oee_result:
        return 0
    values = [
        safe_number(item.get("oee", 0))
        for item in oee_result
    ]
    if not values:
        return 0
    return round(sum(values) / len(values), 2)
def get_worst_machine(oee_result):
    if not oee_result:
        return None
    return min(
        oee_result,
        key=lambda x: safe_number(x.get("oee", 0))
    )
def get_best_machine(oee_result):
    if not oee_result:
        return None
    return max(
        oee_result,
        key=lambda x: safe_number(x.get("oee", 0))
    )
def get_lowest_metric_machine(oee_result, metric_name):
    if not oee_result:
        return None
    return min(
        oee_result,
        key=lambda x: safe_number(x.get(metric_name, 0))
    )
def get_top_downtime_machine(downtime_data):
    if not downtime_data:
        return None, 0
    machine = max(
        downtime_data,
        key=downtime_data.get
    )
    downtime = safe_number(downtime_data.get(machine, 0))
    return machine, round(downtime, 2)
def get_total_downtime(downtime_data):
    if not downtime_data:
        return 0
    return round(
        sum(safe_number(v) for v in downtime_data.values()),
        2
    )
def get_main_loss_category(oee_result):
    """
    Loss calculation:
    Availability Loss = 100 - Availability
    Performance Loss = 100 - Performance
    Quality Loss = 100 - Quality
    Average each loss across machines.
    """
    if not oee_result:
        return None
    availability_losses = []
    performance_losses = []
    quality_losses = []
    for item in oee_result:
        availability = safe_number(item.get("availability", 0))
        performance = safe_number(item.get("performance", 0))
        quality = safe_number(item.get("quality", 0))
        availability_losses.append(max(100 - availability, 0))
        performance_losses.append(max(100 - performance, 0))
        quality_losses.append(max(100 - quality, 0))
    avg_availability_loss = sum(availability_losses) / len(availability_losses)
    avg_performance_loss = sum(performance_losses) / len(performance_losses)
    avg_quality_loss = sum(quality_losses) / len(quality_losses)
    losses = {
        "Availability Loss": avg_availability_loss,
        "Performance Loss": avg_performance_loss,
        "Quality Loss": avg_quality_loss,
    }
    main_loss = max(losses, key=losses.get)
    return {
        "loss_category": main_loss,
        "loss_value": round(losses[main_loss], 2),
        "availability_loss": round(avg_availability_loss, 2),
        "performance_loss": round(avg_performance_loss, 2),
        "quality_loss": round(avg_quality_loss, 2),
    }
    
def generate_daily_insight(oee_result, downtime_data, production_date):
    insights = []
    overall_oee = get_overall_oee(oee_result)
    worst_machine = get_worst_machine(oee_result)
    best_machine = get_best_machine(oee_result)
    top_dt_machine, top_dt_hours = get_top_downtime_machine(downtime_data)
    total_downtime = get_total_downtime(downtime_data)
    low_availability_machine = get_lowest_metric_machine(oee_result, "availability")
    low_performance_machine = get_lowest_metric_machine(oee_result, "performance")
    low_quality_machine = get_lowest_metric_machine(oee_result, "quality")
    # =====================================================
    # 1. OEE_TARGET
    # =====================================================
    if overall_oee >= TARGET_OEE:
        insights.append({
            "type": "OEE_TARGET",
            "priority": "Normal",
            "metric": "OEE",
            "text": (f"Overall OEE was {overall_oee}%, which is above the "f"target of {TARGET_OEE}%.")
        })
    else:
        gap = round(TARGET_OEE - overall_oee, 2)
        insights.append({
            "type": "OEE_TARGET",
            "priority": "High",
            "metric": "OEE",
            "text": (f"Overall OEE was {overall_oee}%, below the target of "f"{TARGET_OEE}% by {gap}%.")
        })
    # =====================================================
    # 2. WORST_MACHINE
    # =====================================================
    if worst_machine:
        machine = worst_machine.get("machine")
        oee = safe_number(worst_machine.get("oee", 0))
        insights.append({
            "type": "WORST_MACHINE",
            "priority": "High" if oee < TARGET_OEE else "Normal",
            "metric": "OEE",
            "machine": machine,
            "text": (f"{machine} had the lowest OEE at {oee}%.")
        })
    # =====================================================
    # 3. BEST_MACHINE
    # =====================================================
    if best_machine:
        machine = best_machine.get("machine")
        oee = safe_number(best_machine.get("oee", 0))
        insights.append({
            "type": "BEST_MACHINE",
            "priority": "Normal",
            "metric": "OEE",
            "machine": machine,
            "text": (f"{machine} had the best OEE performance at {oee}%.")
        })
    # =====================================================
    # 4. DOWNTIME
    # =====================================================
    if top_dt_machine and top_dt_hours > 0:
        insights.append({
            "type": "DOWNTIME",
            "priority": "High",
            "metric": "Downtime",
            "machine": top_dt_machine,
            "text": (f"The highest downtime was from {top_dt_machine}, "f"with {hours_to_time_format(top_dt_hours)} of downtime.")
        })
    else:
        insights.append({
            "type": "DOWNTIME",
            "priority": "Normal",
            "metric": "Downtime",
            "text": ("No significant downtime was recorded for the production date.")
        })
    # =====================================================
    # 5. LOW_AVAILABILITY
    # =====================================================
    if low_availability_machine:
        machine = low_availability_machine.get("machine")
        availability = safe_number(
            low_availability_machine.get("availability", 0)
        )
        if availability < TARGET_AVAILABILITY:
            priority = "High"
        else:
            priority = "Normal"
        insights.append({
            "type": "LOW_AVAILABILITY",
            "priority": priority,
            "metric": "Availability",
            "machine": machine,
            "text": (f"{machine} had the lowest Availability at {availability}%. "f"This indicates time loss from downtime or reduced operating time.")
        })
    # =====================================================
    # 6. LOW_PERFORMANCE
    # =====================================================
    if low_performance_machine:
        machine = low_performance_machine.get("machine")
        performance = safe_number(
            low_performance_machine.get("performance", 0)
        )
        if performance < TARGET_PERFORMANCE:
            priority = "High"
        else:
            priority = "Normal"
        insights.append({
            "type": "LOW_PERFORMANCE",
            "priority": priority,
            "metric": "Performance",
            "machine": machine,
            "text": (f"{machine} had the lowest Performance at {performance}%. "f"This indicates actual output was lower than expected capacity.")
        })
    # =====================================================
    # 7. LOW_QUALITY
    # =====================================================
    if low_quality_machine:
        machine = low_quality_machine.get("machine")
        quality = safe_number(
            low_quality_machine.get("quality", 0)
        )
        if quality < TARGET_QUALITY:
            priority = "High"
        else:
            priority = "Normal"
        insights.append({
            "type": "LOW_QUALITY",
            "priority": priority,
            "metric": "Quality",
            "machine": machine,
            "text": (f"{machine} had the lowest Quality at {quality}%. "f"This indicates quality loss contributed to OEE reduction.")
        })
    # =====================================================
    # 8. MAIN_LOSS_CATEGORY
    # =====================================================
    main_loss = get_main_loss_category(oee_result)
    if main_loss:
        insights.append({
            "type": "MAIN_LOSS_CATEGORY",
            "priority": "High" if main_loss["loss_value"] > 10 else "Normal",
            "metric": "Loss",
            "text": (f"The main loss category was {main_loss['loss_category']}, "f"with an average loss of {main_loss['loss_value']}%.")
        })
    # =====================================================
    # 9. DOWNTIME_CONTRIBUTION
    # =====================================================
    if total_downtime > 0 and top_dt_machine:
        contribution = round(
            (top_dt_hours / total_downtime) * 100,
            1
        )
        insights.append({
            "type": "DOWNTIME_CONTRIBUTION",
            "priority": "High" if contribution >= 50 else "Normal",
            "metric": "Downtime",
            "machine": top_dt_machine,
            "text": (f"{top_dt_machine} accounted for {contribution}% of total "f"downtime, making it the primary downtime contributor.")
        })
    # =====================================================
    # 10. BELOW_TARGET_COUNT
    # =====================================================
    below_target = [
        item for item in oee_result
        if safe_number(item.get("oee", 0)) < TARGET_OEE
    ]
    total_machines = len(oee_result)
    below_count = len(below_target)
    if total_machines > 0:
        insights.append({
            "type": "BELOW_TARGET_COUNT",
            "priority": "High" if below_count > 0 else "Normal",
            "metric": "OEE",
            "text": (f"{below_count} out of {total_machines} machines were below "f"the OEE target of {TARGET_OEE}%.")
        })
    # =====================================================
    # 11. ZERO_DOWNTIME_LOW_OEE
    # =====================================================
    for item in oee_result:
        machine = item.get("machine")
        oee = safe_number(item.get("oee", 0))
        downtime = safe_number(item.get("downtime", 0))
        performance = safe_number(item.get("performance", 0))
        quality = safe_number(item.get("quality", 0))
        if downtime == 0 and oee < TARGET_OEE:
            likely_issue = "Performance"
            if quality < TARGET_QUALITY and quality < performance:
                likely_issue = "Quality"
            insights.append({
                "type": "ZERO_DOWNTIME_LOW_OEE",
                "priority": "High",
                "metric": "OEE",
                "machine": machine,
                "text": (f"{machine} had no recorded downtime, but OEE remained "f"below target at {oee}%. The main issue is likely related "f"to {likely_issue} loss.")
            })
    # =====================================================
    # 12. ACTION_FOCUS
    # =====================================================
    action_points = []
    if worst_machine:
        action_points.append(f"review {worst_machine.get('machine')} OEE loss")
    if top_dt_machine and top_dt_hours > 0:
        action_points.append(f"reduce downtime on {top_dt_machine}")
    if low_performance_machine:
        performance = safe_number(low_performance_machine.get("performance", 0))
        if performance < TARGET_PERFORMANCE:
            action_points.append(f"investigate low Performance on {low_performance_machine.get('machine')}")
    if low_quality_machine:
        quality = safe_number(low_quality_machine.get("quality", 0))
        if quality < TARGET_QUALITY:
            action_points.append(f"investigate Quality loss on {low_quality_machine.get('machine')}")
    # remove duplicate action points
    action_points = list(dict.fromkeys(action_points))
    if action_points:
        action_text = "; ".join(action_points[:3])
        insights.append({
            "type": "ACTION_FOCUS",
            "priority": "High",
            "metric": "Action",
            "text": (f"Recommended focus: {action_text}.")
        })
    else:
        insights.append({
            "type": "ACTION_FOCUS",
            "priority": "Normal",
            "metric": "Action",
            "text": ("Recommended focus: continue monitoring OEE performance and downtime trend.")
        })
    return insights