import json
import os
import tempfile
from configparser import ConfigParser
from copy import deepcopy
from datetime import date, datetime, timedelta, time
from pathlib import Path

SCHEMA_VERSION = 1
PRODUCTION_START_TIME = time(0, 0)  # production day = D 00:00 -> D+1 00:00

def load_history_dir(config_path="config/config.ini"):
    config = ConfigParser()
    if not config.read(config_path, encoding="utf-8"):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not config.has_section("HISTORY"):
        raise KeyError("Missing [HISTORY] section in config.ini")
    history_path = config.get("HISTORY", "PATH", fallback="").strip()
    if not history_path:
        raise ValueError("HISTORY path is empty in config.ini")
    return Path(history_path)
def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )
def get_production_date(result):
    if not isinstance(result, dict):
        raise TypeError("Snapshot result must be a dictionary")
    overall = result.get("overall")
    if not isinstance(overall, dict):
        raise ValueError("Snapshot result is missing 'overall' dictionary")
    production_date = overall.get("production_date")
    if isinstance(production_date, datetime):
        production_date = production_date.date()
    elif isinstance(production_date, str):
        try:
            production_date = date.fromisoformat(production_date)
        except ValueError as exc:
            raise ValueError(
                f"Invalid production_date: {production_date}"
            ) from exc
    if not isinstance(production_date, date):
        raise ValueError(
            "overall.production_date must be date, datetime or YYYY-MM-DD string"
        )
    return production_date
def validate_snapshot_result(result):
    if not isinstance(result, dict):
        raise TypeError("Result must be a dictionary")
    machines = result.get("machines")
    if not isinstance(machines, dict):
        raise ValueError("Result is missing 'machines' dictionary")
    if not machines:
        raise ValueError("Result contains no machine data")
    get_production_date(result)
    for machine_name, machine in machines.items():
        if not isinstance(machine_name, str) or not machine_name.strip():
            raise ValueError("Invalid machine name")
        if not isinstance(machine, dict):
            raise ValueError(
                f"Machine '{machine_name}' data must be a dictionary"
            )
        for field in ("oee", "availability", "performance", "quality"):
            value = machine.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"{machine_name}.{field} must be numeric"
                )
        downtime_detail = machine.get("downtime_detail", {})
        if downtime_detail is None:
            downtime_detail = {}
        if not isinstance(downtime_detail, dict):
            raise ValueError(
                f"{machine_name}.downtime_detail must be a dictionary"
            )
        for category, hours in downtime_detail.items():
            if not isinstance(category, str):
                raise ValueError(
                    f"{machine_name} downtime category must be text"
                )
            if not isinstance(hours, (int, float)):
                raise ValueError(
                    f"{machine_name} downtime '{category}' must be numeric"
                )
            if hours < 0:
                raise ValueError(
                    f"{machine_name} downtime '{category}' cannot be negative"
                )
    # Important:
    # We intentionally DO NOT require sum(downtime_detail)
    # to equal actual downtime because categories may overlap.
def build_snapshot(result, status="FINAL"):
    validate_snapshot_result(result)
    production_date = get_production_date(result)
    period_start = datetime.combine(
        production_date,
        PRODUCTION_START_TIME
    )
    period_end = period_start + timedelta(days=1)
    snapshot = deepcopy(result)
    # Convert nested production_date to JSON-friendly ISO string.
    snapshot.setdefault("overall", {})
    snapshot["overall"]["production_date"] = production_date.isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "production_date": production_date.isoformat(),
        "period": {
            "start": period_start.strftime("%Y-%m-%d %H:%M"),
            "end": period_end.strftime("%Y-%m-%d %H:%M")
        },
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "status": status,
        "overall": snapshot.get("overall", {}),
        "machines": snapshot.get("machines", {})
    }
def atomic_write_json(snapshot, destination):
    destination = Path(destination)
    history_dir = destination.parent
    # We intentionally fail here if Shared Drive is unavailable.
    if not history_dir.exists():
        raise FileNotFoundError(
            f"OEE history storage is unavailable: {history_dir}"
        )
    if not history_dir.is_dir():
        raise NotADirectoryError(
            f"OEE history path is not a directory: {history_dir}"
        )
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            prefix="oee_",
            dir=history_dir,
            delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                snapshot,
                temp_file,
                ensure_ascii=False,
                indent=2,
                default=json_default,
                allow_nan=False
            )
            temp_file.flush()
            os.fsync(temp_file.fileno())
        # Replace only after complete JSON was successfully written.
        os.replace(temp_path, destination)
    except Exception:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
def save_daily_snapshot(
    result,
    config_path="config/config.ini",
    status="FINAL"
):
    history_dir = load_history_dir(config_path)
    snapshot = build_snapshot(result, status=status)
    production_date = snapshot["production_date"]
    # Filename is generated only from validated production_date.
    destination = history_dir / f"{production_date}.json"
    atomic_write_json(
        snapshot,
        destination
    )
    return destination