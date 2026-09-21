import json
import logging
import re
from configparser import ConfigParser
from datetime import date
from pathlib import Path
from flask import Flask, jsonify, render_template, request
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.ini"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_JSON_SIZE = 5 * 1024 * 1024  # 5 MB
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("oee-dashboard")
def load_history_dir():
    config = ConfigParser()
    if not config.read(CONFIG_PATH, encoding="utf-8"):
        raise FileNotFoundError("Configuration file is unavailable")
    if not config.has_section("HISTORY"):
        raise RuntimeError("Missing HISTORY configuration")
    history_path = config.get(
        "HISTORY",
        "path",
        fallback=""
    ).strip()
    if not history_path:
        raise RuntimeError("HISTORY path is not configured")
    return Path(history_path)
def validate_date_string(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not DATE_PATTERN.fullmatch(value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    # Ensures normalized YYYY-MM-DD format.
    if parsed.isoformat() != value:
        return None
    return value
def get_available_dates():
    history_dir = load_history_dir()
    if not history_dir.exists():
        raise FileNotFoundError("OEE history storage is unavailable")
    if not history_dir.is_dir():
        raise NotADirectoryError("OEE history storage is invalid")
    available_dates = []
    for file_path in history_dir.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() != ".json":
            continue
        date_string = validate_date_string(file_path.stem)
        if date_string:
            available_dates.append(date_string)
    return sorted(set(available_dates))
def get_snapshot_path(date_string):
    valid_date = validate_date_string(date_string)
    if not valid_date:
        raise ValueError("Invalid production date")
    history_dir = load_history_dir()
    if not history_dir.exists():
        raise FileNotFoundError("OEE history storage is unavailable")
    if not history_dir.is_dir():
        raise NotADirectoryError("OEE history storage is invalid")
    # Filename is generated from validated ISO date only.
    return history_dir / f"{valid_date}.json"
def read_snapshot(date_string):
    snapshot_path = get_snapshot_path(date_string)
    if not snapshot_path.exists():
        raise FileNotFoundError("Snapshot not found")
    if not snapshot_path.is_file():
        raise FileNotFoundError("Snapshot not found")
    file_size = snapshot_path.stat().st_size
    if file_size <= 0:
        raise ValueError("Snapshot file is empty")
    if file_size > MAX_JSON_SIZE:
        raise ValueError("Snapshot file is too large")
    with snapshot_path.open(
        "r",
        encoding="utf-8"
    ) as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Invalid snapshot format")
    snapshot_date = data.get("production_date")
    if snapshot_date != date_string:
        raise ValueError("Snapshot production date mismatch")
    if not isinstance(data.get("machines"), dict):
        raise ValueError("Snapshot machine data is invalid")
    if not isinstance(data.get("overall"), dict):
        raise ValueError("Snapshot overall data is invalid")
    return data
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    # index.html currently contains inline CSS/JS,
    # so unsafe-inline is required for V1.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    return response
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")
@app.route("/api/oee/dates", methods=["GET"])
def api_dates():
    try:
        available_dates = get_available_dates()
        return jsonify({
            "dates": available_dates
        })
    except (
        FileNotFoundError,
        NotADirectoryError,
        PermissionError,
        OSError
    ) as exc:
        logger.error(
            "Unable to access OEE history storage: %s",
            exc
        )
        return jsonify({
            "error": "History storage unavailable"
        }), 503
    except Exception:
        logger.exception(
            "Unexpected error while reading available dates"
        )
        return jsonify({
            "error": "Unable to load OEE dates"
        }), 500
@app.route("/api/oee/dashboard", methods=["GET"])
def api_dashboard():
    requested_date = request.args.get(
        "date",
        "",
        type=str
    ).strip()
    # If no date is supplied, return latest available snapshot.
    if not requested_date:
        try:
            available_dates = get_available_dates()
            if not available_dates:
                return jsonify({
                    "error": "No OEE data available"
                }), 404
            requested_date = available_dates[-1]
        except (
            FileNotFoundError,
            NotADirectoryError,
            PermissionError,
            OSError
        ) as exc:
            logger.error(
                "Unable to access OEE history storage: %s",
                exc
            )
            return jsonify({
                "error": "History storage unavailable"
            }), 503
    if not validate_date_string(requested_date):
        return jsonify({
            "error": "Invalid date format"
        }), 400
    try:
        snapshot = read_snapshot(requested_date)
        return jsonify(snapshot)
    except FileNotFoundError:
        return jsonify({
            "error": "OEE data not found for selected date"
        }), 404
    except (
        PermissionError,
        NotADirectoryError,
        OSError
    ) as exc:
        logger.error(
            "Unable to access OEE snapshot storage: %s",
            exc
        )
        return jsonify({
            "error": "History storage unavailable"
        }), 503
    except (
        json.JSONDecodeError,
        ValueError
    ) as exc:
        logger.error(
            "Invalid snapshot for %s: %s",
            requested_date,
            exc
        )
        return jsonify({
            "error": "OEE snapshot is invalid"
        }), 500
    except Exception:
        logger.exception(
            "Unexpected dashboard error for %s",
            requested_date
        )
        return jsonify({
            "error": "Unable to load OEE dashboard"
        }), 500
@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "error": "Resource not found"
    }), 404
@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({
        "error": "Method not allowed"
    }), 405
if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )