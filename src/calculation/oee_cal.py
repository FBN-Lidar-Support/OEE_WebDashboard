PLANNED_TIME = 21
TARGET_OEE = 85

def hours_to_time_format(hours):
    """
    Convert decimal hours to h:mm format.
    Example:
    1.45 -> 1:27
    2.0  -> 2:00
    0    -> 0:00
    """
    try:
        total_minutes = round(float(hours) * 60)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}:{m:02d}"
    except Exception:
        return "0:00"
    
def calculate_oee(downtime_data, yield_data):
    result = []
    print("="*50)
    print(downtime_data)
    print("="*50)
    print(yield_data)
    print("="*50)
    for machine, data in yield_data.items():
        
        downtime = downtime_data.get(machine, 0)
        
        operating_time = max(PLANNED_TIME - downtime, 0.01)
        
        availability = operating_time / PLANNED_TIME
        
        performance = (data["total_last_opn"] / (data["ideal_speed"] * operating_time))
        
        quality = (data["pass_last_opn"] / data["input_first_opn"])
        
        oee = availability * performance * quality
        
        oee_percent = round(oee * 100, 2)
        
        result.append({
            "machine": machine,
            "downtime": round(downtime, 2),
            "downtime_display": hours_to_time_format(downtime),
            "availability": round(availability * 100, 2),
            "performance": round(performance * 100, 2),
            "quality": round(quality * 100, 2),
            "oee": oee_percent,
            "target_oee": TARGET_OEE,
            "status": "PASS" if oee_percent >= TARGET_OEE else "FAIL"
        })
    return result

