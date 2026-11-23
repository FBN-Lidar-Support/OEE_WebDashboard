"""Calculate OEE for each physical machine (no group OEE)."""
import configparser
import math
from pathlib import Path
from platform import machine
import re
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.ini"
PROCESS_SETS = {
    "AB2B": ("AB2B", "AB2B_POST_TEST"),
    "AA": ("AA_FAS_SAS", "AA_FAS_SAS_POST_OVEN", "AA_TP", "AA_TP_POST_OVEN"),
    "IEOL_Bringup_CRS": ("IEOL_BRINGUP", "IEOL_CRS"),
    "IEOL_SHORT": ("IEOL_SHORT",),
    "IEOL_LONG": ("IEOL_LONG",),
    "TPL01": ("TPL01",)
}
ALIASES = {"IEOL_S": "IEOL_SHORT", "IEOL_L": "IEOL_LONG"}
COUNTS = ("input_first_opn", "total_last_opn", "pass_last_opn")
def _number(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid number: {name}")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid number: {name}")
    return value
def _machine_name(name):
    name = str(name).strip().upper()
    name = re.sub(r"^ORA#\d+\s+", "", name)
    if name == "IEOL_BRINGUP_CRS":
        return "IEOL_BRINGUP_CRS01"
    return name
def _section(config, name):
    name = name.upper()
    candidates = [name]
    if name == "IEOL_SHORT":
        candidates.append("IEOL_S")
    elif name == "IEOL_LONG":
        candidates.append("IEOL_L")
    match = next((s for s in config.sections() if s.upper() in candidates), None)
    if match is None:
        raise ValueError(f"Missing config section: [{name}]")
    return config[match]
def _empty():
    return {
        **{field: 0 for field in COUNTS},
        "duration_hr": 0.0,
        "ideal_time": 0.0,
        "good_ideal_time": 0.0,
        "steps": {},
        "speeds": {}
    }
def format_ideal_speed(speeds):
    """{"AA_FAS_SAS": 2.43, "AA_TP": 95.24} -> "AA_FAS_SAS 2.43, AA_TP 95.24 unit/hr"."""
    if not speeds:
        return None
    if len(speeds) == 1:
        return f"{next(iter(speeds.values())):g} unit/hr"
    return ", ".join(f"{process} {speed:g}" for process, speed in speeds.items()) + " unit/hr"
def hours_to_time_format(hours):
    minutes = round(hours * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"
def reconcile_machine_time(planned_time, raw_downtime, active_time):
    """Operating time is FITS active time only.
    Planned time = FITS active + downtime + unknown. Unknown is time that is
    neither FITS active nor recorded downtime (downtime not keyed in, material
    shortage, ...). It is NOT operating time: until operators record it as
    downtime it lowers Availability. FITS active still takes precedence if
    recorded downtime overlaps it. The original downtime is retained; this
    does not modify source CSVs.
    """
    planned = _number(planned_time, "planned_time")
    raw_dt = _number(raw_downtime, "raw_downtime")
    active = _number(active_time, "active_time")
    if planned <= 0:
        raise ValueError("Planned Time must be positive")
    if raw_dt > planned + 1e-6:
        raise ValueError(f"Downtime {raw_dt} hr exceeds Planned Time {planned} hr")
    if active > planned + 1e-6:
        raise ValueError(f"Active Time {active} hr exceeds Planned Time {planned} hr")
    raw_dt = min(raw_dt, planned)
    active = min(active, planned)
    operating = active
    adjusted_dt = min(raw_dt, planned - active)
    unknown = max(planned - active - adjusted_dt, 0.0)
    return {
        "planned_time": planned,
        "raw_downtime": raw_dt,
        "downtime": adjusted_dt,
        "operating_time": operating,
        "active_time": active,
        "unknown_time": unknown,
        "downtime_adjustment": raw_dt - adjusted_dt
    }
def build_time_bar_data(time_data, ideal_time, raw_types=None):
    """Create per-machine, 21-hour stacked-bar data without double counting.
    Raw downtime categories are recorded facts. When FITS active time overrides
    downtime, category-level adjusted hours are estimates, not measured events.
    """
    planned = time_data["planned_time"]
    raw_dt = time_data["raw_downtime"]
    adjusted_dt = time_data["downtime"]
    active = time_data["active_time"]
    unknown = time_data["unknown_time"]
    categories = {
        str(name): _number(hours, f"downtime type {name}")
        for name, hours in (raw_types or {}).items()
        if _number(hours, f"downtime type {name}") > 0
    }
    raw_sum = sum(categories.values())
    estimated = time_data["downtime_adjustment"] > 1e-6
    if adjusted_dt <= 1e-9:
        adjusted_types = {}
        allocation = "NO_ADJUSTED_DOWNTIME"
    elif categories and abs(raw_sum - raw_dt) <= 1e-4:
        adjusted_types = {
            name: adjusted_dt * hours / raw_sum
            for name, hours in categories.items()
        }
        allocation = "PROPORTIONAL_ESTIMATE" if estimated else "RAW_TYPES_MATCH"
    else:
        adjusted_types = {"Unclassified Downtime": adjusted_dt}
        allocation = "UNALLOCATED_TYPE_MISMATCH" if categories else "NO_TYPE_DATA"
    segments = [
        {
            "key": f"downtime_{index}", "kind": "downtime", "label": name,
            "hours": round(hours, 6), "estimated": estimated
        }
        for index, (name, hours) in enumerate(adjusted_types.items())
        if hours > 1e-9
    ]
    segments.extend([
        {"key": "active", "kind": "active", "label": "Actual Run Time", "hours": round(active, 6)},
        {"key": "unknown", "kind": "unknown", "label": "Unknown / Unclassified", "hours": round(unknown, 6)}
    ])
    return {
        "max_hours": round(planned, 6),
        "raw_downtime": round(raw_dt, 6),
        "downtime": round(adjusted_dt, 6),
        "operating_time": round(time_data["operating_time"], 6),
        "active_time": round(active, 6),
        "unknown_time": round(unknown, 6),
        "segments": segments,
        "ideal_time": round(ideal_time, 6),
        "raw_downtime_by_type": {k: round(v, 6) for k, v in categories.items()},
        "adjusted_downtime_by_type": {k: round(v, 6) for k, v in adjusted_types.items()},
        "allocation_method": allocation,
        "downtime_adjustment": round(time_data["downtime_adjustment"], 6)
    }
def _metrics(data, downtime, planned, targets, weighted_quality, quality_ok, time_data=None, issues=None):
    active = _number(data["duration_hr"], "duration_hr")
    ideal = _number(data["ideal_time"], "ideal_time")
    if time_data is None:
        time_data = reconcile_machine_time(planned, downtime, active)
    operating = time_data["operating_time"]
    adjusted_dt = time_data["downtime"]
    unknown = time_data["unknown_time"]
    availability = operating / planned
    # P = Pieces Produced / (Ideal Speed [pcs/hr] * Operating Time).
    # For multiple processes/speeds, ideal = sum(output_i / speed_i).
    performance = ideal / operating if operating > 0 else (0.0 if ideal == 0 else None)
    # Q = Acceptable Pieces / Total Pieces.
    numerator = _number(data["pass_last_opn"], "pass_last_opn")
    denominator = _number(data["total_last_opn"], "total_last_opn")
    quality = numerator / denominator if denominator > 0 else (0.0 if numerator == 0 else None)
    issues = list(issues or [])
    if active == 0 and ideal > 0:
        issues.append("MISSING_FITS_ACTIVE_TIME")
    if performance is None:
        issues.append("PERFORMANCE_UNDEFINED")
    # Performance > 100% is NOT a data-quality issue: it means the machine ran
    # faster than IDEAL_SPEED (or FITS active time is short). It is explained
    # in the Smart Insight text (src/analytics/smart_insight.py) instead.
    if quality is None:
        issues.append("QUALITY_UNDEFINED")
    elif quality > 1.000001:
        issues.append("QUALITY_OVER_100")
    quality_ok = bool(quality_ok and not issues)
    # Checked AFTER all issues above are collected: if the machine's data is
    # incomplete for any reason, A/P/Q must not show ACHIEVED / BELOW TARGET
    # either (previously only OEE did, so e.g. Q showed ACHIEVED in green).
    base_ok = quality_ok
    oee =availability * performance * quality if performance is not None and quality is not None else None
    percentages = {
        "oee": round(oee * 100, 2) if oee is not None else None,
        "availability": round(availability * 100, 2),
        "performance": round(performance * 100, 2) if performance is not None else None,
        "quality": round(quality * 100, 2) if quality is not None else None
    }
    names = {"oee": "oee", "availability": "a", "performance": "p", "quality": "q"}
    incomplete = {
        "oee": not quality_ok or percentages["oee"] is None,
        "availability": not base_ok,
        "performance": not base_ok or performance is None,
        "quality": not base_ok or quality is None or quality > 1.000001,
    }
    statuses = {
        f"{short}_status": (
            "DATA INCOMPLETE" if incomplete[name]
            else "ACHIEVED" if percentages[name] >= targets[name]
            else "BELOW TARGET"
        )
        for name, short in names.items()
    }
    detail = {
        "input_first_opn": data["input_first_opn"],
        "output_last_opn": data["total_last_opn"],
        "pass_last_opn": data["pass_last_opn"],
        "pieces_produced": data["total_last_opn"],
        "acceptable_pieces": data["pass_last_opn"],
        "total_pieces": data["total_last_opn"],
        "planned_time": round(planned, 4),
        "operating_time": round(operating, 4),
        "active_time": round(active, 6),
        "unknown_time": round(unknown, 6),
        "non_active_time": round(unknown, 4),
        "ideal_time": round(ideal, 6)
    }
    return {
        **percentages,
        "raw_downtime": round(time_data["raw_downtime"], 6),
        "downtime": round(adjusted_dt, 6),
        "adjusted_downtime": round(adjusted_dt, 6),
        "downtime_adjustment": round(time_data["downtime_adjustment"], 6),
        "downtime_display": hours_to_time_format(adjusted_dt),
        "target": targets,
        **statuses,
        "data_quality_ok": quality_ok,
        "data_quality_issues": issues,
        "detail": detail
    }
def calculate_oee(downtime_data, yield_data, Active_time=None, downtime_type_data=None,
                  downtime_issues=None):
    """Return a flat dictionary of OEE results keyed by physical machine.
    ``downtime_issues``: optional {machine: [message, ...]} of downtime rows the
    ETL skipped as invalid; those machines are marked DATA INCOMPLETE.
    """
    skipped_rows = {}
    for name, messages in (downtime_issues or {}).items():
        if messages:
            skipped_rows.setdefault(_machine_name(name), []).extend(messages)
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(CONFIG_PATH, encoding="utf-8-sig"):
        raise FileNotFoundError(f"Cannot read config: {CONFIG_PATH}")
    yields = {}
    for key, value in yield_data.items():
        name = ALIASES.get(str(key).upper(), str(key).upper())
        if name in yields:
            raise ValueError(f"Duplicate yield process: {name}")
        yields[name] = value
    downtime = {}
    for name, hours in downtime_data.items():
        machine = _machine_name(name)
        if machine in downtime:
            raise ValueError(f"Duplicate downtime machine: {machine}")
        downtime[machine] = _number(hours, f"{name} downtime")
    downtime_types = {}
    for name, types in (downtime_type_data or {}).items():
        machine = _machine_name(name)
        if machine in downtime_types:
            raise ValueError(f"Duplicate downtime type machine: {machine}")
        if not isinstance(types, dict):
            raise ValueError(f"Invalid downtime type data for {name}")
        downtime_types[machine] = types
    result = {}
    for set_name, processes in PROCESS_SETS.items():
        present = [p for p in processes if p in yields]
        if not present:
            continue
        missing = [p for p in processes if p not in yields]
        settings = _section(config, "AA_TP" if set_name == "AA" else present[0])
        planned_each = _number(settings.get("PLANNED_TIME", "21"), "PLANNED_TIME")
        if planned_each <= 0:
            raise ValueError(f"Invalid PLANNED_TIME for {set_name}")
        targets = {
            "oee": settings.getfloat("TARGET_OEE", fallback=85),
            "availability": settings.getfloat("TARGET_A", fallback=95),
            "performance": settings.getfloat("TARGET_P", fallback=85),
            "quality": settings.getfloat("TARGET_Q", fallback=98)
        }
        machines = {}
        machine_issues = {}
        for process in present:
            item = yields[process]
            cfg = _section(config, process)
            speed = _number(cfg.get("IDEAL_SPEED", "0"), f"{process} IDEAL_SPEED")
            if speed <= 0:
                raise ValueError(f"Invalid IDEAL_SPEED for {process}")
            process_issues = []
            if not item.get("data_quality_ok", True):
                process_issues.append(f"FITS_DATA_QUALITY:{process}")
            if item.get("uncount"):
                process_issues.append(f"UNCOUNT:{process}")
            for field in (COUNTS if not item.get("uncount") else ()):
                total = sum(
                    _number(values[field], f"{process}.{field}")
                    for values in item["machines"].values()
                )
                if abs(total - _number(item[field], f"{process}.{field}")) > 1e-6:
                    process_issues.append(f"YIELD_TOTAL_MISMATCH:{process}.{field}")
            duration_total = sum(
                _number(values["duration_hr"], f"{process}.duration_hr")
                for values in item["machines"].values()
            )
            if abs(duration_total - _number(item["duration_hr"], f"{process}.duration_hr")) > 1e-4:
                process_issues.append(f"FITS_DURATION_MISMATCH:{process}")
            for name, values in item["machines"].items():
                machine = _machine_name(name)
                stats = machines.setdefault(machine, _empty())
                issues = machine_issues.setdefault(machine, [])
                for issue in process_issues:
                    if issue not in issues:
                        issues.append(issue)
                for field in COUNTS:
                    stats[field] += _number(values[field], f"{machine}.{field}")
                stats["duration_hr"] += _number(values["duration_hr"], f"{machine}.duration_hr")
                produced = _number(values["total_last_opn"], f"{machine}.total_last_opn")
                stats["ideal_time"] += produced / speed
                stats["good_ideal_time"] += _number(values["pass_last_opn"], f"{machine}.pass") / speed
                stats["steps"][process] = dict(values)
                stats["speeds"][process] = speed
        if not machines:
            raise ValueError(f"No machines in yield data for {set_name}")
        for machine, stats in sorted(machines.items()):
            if machine in result:
                raise ValueError(f"Machine appears in multiple process sets: {machine}")
            issues = machine_issues[machine]
            for process in missing:
                issues.append(f"MISSING_PROCESS:{process}")
            if machine not in downtime:
                # No downtime CSV for this machine: assume 0 hr but flag it,
                # instead of failing the whole daily report.
                issues.append("MISSING_DOWNTIME_FILE")
            if machine in skipped_rows:
                issues.append(f"DOWNTIME_ROWS_SKIPPED:{len(skipped_rows[machine])}")
            raw_dt = downtime.get(machine, 0.0)
            active = stats["duration_hr"]
            if raw_dt > planned_each + 1e-6:
                issues.append("DOWNTIME_EXCEEDS_PLANNED")
            if active > planned_each + 1e-6:
                issues.append("ACTIVE_EXCEEDS_PLANNED")
            stats["duration_hr"] = min(active, planned_each)
            time_data = reconcile_machine_time(
                planned_each, min(raw_dt, planned_each), stats["duration_hr"]
            )
            row = _metrics(
                stats, raw_dt, planned_each, targets,
                False, not issues, time_data, issues
            )
            row["detail"]["steps"] = stats["steps"]
            row["detail"]["processes"] = sorted(stats["steps"])
            row["detail"]["ideal_speed"] = format_ideal_speed(stats["speeds"])
            row["time_bar"] = build_time_bar_data(
                time_data, stats["ideal_time"], downtime_types.get(machine)
            )
            row["missing_processes"] = missing
            # Exact rows to fix in the downtime CSV (shown with the issue list).
            row["downtime_skipped_rows"] = skipped_rows.get(machine, [])
            result[machine] = row
    return result