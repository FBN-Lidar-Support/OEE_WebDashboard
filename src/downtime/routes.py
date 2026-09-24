import configparser
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request
from .service import (ConflictError, DowntimeStore, StorageError, ValidationError)

def create_downtime_blueprint(config_path):
    config = configparser.ConfigParser()
    if not config.read(Path(config_path), encoding="utf-8"):
        raise RuntimeError("Unable to read config.ini")
    if "DOWNTIME" not in config:
        raise RuntimeError("Missing [DOWNTIME] section.")
    record_dir = config["DOWNTIME"].get("record_path", "").strip()
    type_dir = config["DOWNTIME"].get("type_path", "").strip()
    if not record_dir or not type_dir:
        raise RuntimeError("Downtime path missing.")
    store = DowntimeStore(record_dir, type_dir)
    bp = Blueprint("downtime", __name__)
    @bp.get("/downtime")
    def downtime_page():
        return render_template("downtime.html")
    @bp.get("/api/downtime/machines")
    def get_machines():
        try:
            return jsonify({"machines": store.list_machines()})
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.get("/api/downtime/types")
    def get_types():
        try:
            machine = request.args.get("machine", "")
            return jsonify({
                "machine": machine,
                "types": store.get_downtime_types(machine)
            })
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.get("/api/downtime/open")
    def get_open():
        try:
            machine = request.args.get("machine", "")
            return jsonify({
                "machine": machine,
                "records": store.get_open_downtime(machine)
            })
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.post("/api/downtime/open")
    def add_downtime():
        if not request.is_json:
            return jsonify({"error": "JSON request required."}), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid request."}), 400
        try:
            record = store.add_downtime(
                machine=payload.get("machine"),
                downtime_type=payload.get("type"),
                detail=payload.get("detail"),
                en_checkin=payload.get("en_checkin"),
                checkin_iso=payload.get("checkin")
            )
            return jsonify({
                "message": "Downtime added successfully.",
                "record": record
            }), 201
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.post("/api/downtime/close")
    def close_downtime():
        if not request.is_json:
            return jsonify({"error": "JSON request required."}), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid request."}), 400
        try:
            count = store.close_downtime(
                machine=payload.get("machine"),
                items=payload.get("items"),
                en_checkout=payload.get("en_checkout")
            )
            return jsonify({
                "message": f"{count} downtime record(s) closed.",
                "updated": count
            })
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except ConflictError as e:
            return jsonify({"error": str(e)}), 409
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    return bp