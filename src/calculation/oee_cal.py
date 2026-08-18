import configparser
CONFIG_PATH = r"C:\Projects\oee-dashboard\config\config.ini"
# ==========================================================
# Helper
# ==========================================================
def hours_to_time_format(hours):
    try:
        total_minutes = round(float(hours) * 60)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}:{m:02d}"
    except Exception:
        return "0:00"
# ==========================================================
# OEE Calculation
# ==========================================================
def calculate_oee(downtime_data, yield_data):
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    result = {}
    for machine, data in yield_data.items():
        ####################################################
        # Skip AA_FAS_SAS
        ####################################################
        if machine == "AA_FAS_SAS":
            continue
        ####################################################
        # Config
        ####################################################
        cfg = config[machine]
        PLANNED_TIME = cfg.getfloat("PLANNED_TIME", 21)
        TARGET_OEE = cfg.getfloat("TARGET_OEE", 85)
        TARGET_A = cfg.getfloat("TARGET_A", 95)
        TARGET_P = cfg.getfloat("TARGET_P", 85)
        TARGET_Q = cfg.getfloat("TARGET_Q", 98)
        IDEAL_SPEED = cfg.getfloat("IDEAL_SPEED", 1)
        ####################################################
        # AA
        ####################################################
        if machine == "AA_TP":
            fas = yield_data["AA_FAS_SAS"]
            tp = yield_data["AA_TP"]
            fas_cfg = config["AA_FAS_SAS"]
            tp_cfg = config["AA_TP"]
            FAS_IDEAL_SPEED = fas_cfg.getfloat("IDEAL_SPEED", 1)
            TP_IDEAL_SPEED = tp_cfg.getfloat("IDEAL_SPEED", 1)
            machine_name = "AA"
            downtime = downtime_data.get(machine_name, 0)
            planned_time = PLANNED_TIME * 2
            operating_time = max(planned_time - downtime, 0.01)
            ################################################
            # Availability
            ################################################
            availability = (operating_time / planned_time)
            ################################################
            # Performance
            ################################################
            ideal_time = (fas["input_first_opn"] / FAS_IDEAL_SPEED + tp["input_first_opn"] / TP_IDEAL_SPEED)
            performance = (ideal_time / operating_time)
            ################################################
            # Quality
            ################################################
            good_ideal_time = (fas["pass_last_opn"] / FAS_IDEAL_SPEED + tp["pass_last_opn"] / TP_IDEAL_SPEED)
            quality = (good_ideal_time / ideal_time if ideal_time > 0 else 0)
            ################################################
            # Detail
            ################################################
            detail = {
                "input_first_opn": {
                    "FAS_SAS": fas["input_first_opn"],
                    "TP": tp["input_first_opn"]
                },
                "output_last_opn": {
                    "FAS_SAS": fas["total_last_opn"],
                    "TP": tp["total_last_opn"]
                },
                "pass_last_opn": {
                    "FAS_SAS": fas["pass_last_opn"],
                    "TP": tp["pass_last_opn"]
                },
                "ideal_speed": {
                    "FAS_SAS": f"{FAS_IDEAL_SPEED} unit / hrs.",
                    "TP": f"{TP_IDEAL_SPEED} unit / hrs."
                }
            }
        ####################################################
        # Normal Machine
        ####################################################
        else:
            machine_name = machine
            downtime = downtime_data.get(machine_name, 0)
            planned_time = PLANNED_TIME
            operating_time = max(planned_time - downtime, 0.01)
            ################################################
            # Availability
            ################################################
            availability = (operating_time / planned_time)
            ################################################
            # Performance
            ################################################
            performance = (data["total_last_opn"] / (IDEAL_SPEED * operating_time))
            ################################################
            # Quality
            ################################################
            quality = (data["pass_last_opn"] / data["input_first_opn"] if data["input_first_opn"] > 0 else 0)
            ################################################
            # Detail
            ################################################
            detail = {
                "input_first_opn": data["input_first_opn"],
                "output_last_opn": data["total_last_opn"],
                "pass_last_opn": data["pass_last_opn"],
                "ideal_speed": f"{IDEAL_SPEED} unit / hrs."
            }
        ####################################################
        # OEE
        ####################################################
        oee = (availability * performance * quality)
        oee_percent = round(oee * 100, 2)
        a_percent = round(availability * 100, 2)
        p_percent = round(performance * 100, 2)
        q_percent = round(quality * 100, 2)
        ####################################################
        # Result
        ####################################################
        result[machine_name] = {
            "oee": oee_percent,
            "availability":a_percent,
            "performance":p_percent,
            "quality": q_percent,
            "downtime": round(downtime, 2),
            "downtime_display": hours_to_time_format(downtime),
            "target": {
                "oee": TARGET_OEE,
                "availability": TARGET_A,
                "performance": TARGET_P,
                "quality": TARGET_Q,
            },
            "oee_status": ("ACHIEVED" if oee_percent >= TARGET_OEE else "BELOW TARGET"),
            "a_status": ("ACHIEVED" if a_percent >= TARGET_A else "BELOW TARGET"),
            "p_status": ("ACHIEVED" if p_percent >= TARGET_P else "BELOW TARGET"),
            "q_status": ("ACHIEVED" if q_percent >= TARGET_Q else "BELOW TARGET"),
            "detail": detail
        }
    return result