import configparser
import csv
import io
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, send_file
from .service import ConflictError, DowntimeStore, StorageError, ValidationError

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
    @bp.get("/api/downtime/lines")
    def get_lines():
        try:
            return jsonify({"lines": store.list_lines()})
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.get("/api/downtime/machines")
    def get_machines():
        try:
            line = request.args.get("line", "")
            return jsonify({
                "line": line,
                "machines": store.list_machines(line)
            })
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.get("/api/downtime/types")
    def get_types():
        try:
            line = request.args.get("line", "")
            machine = request.args.get("machine", "")
            return jsonify({
                "line": line,
                "machine": machine,
                "types": store.get_downtime_types(line, machine)
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
                line=payload.get("line"),
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
    @bp.get("/api/downtime/history")
    def get_history():
        try:
            data = store.get_downtime_history(
                line=request.args.get("line", ""),
                machine=request.args.get("machine", ""),
                from_date=request.args.get("from_date", ""),
                to_date=request.args.get("to_date", "")
            )
            return jsonify(data)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    @bp.get("/api/downtime/history/download")
    def download_history():
        try:
            data = store.get_downtime_history(
                line=request.args.get("line", ""),
                machine=request.args.get("machine", ""),
                from_date=request.args.get("from_date", ""),
                to_date=request.args.get("to_date", "")
            )
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data["records"])
            csv_bytes = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8"))
            csv_bytes.seek(0)
            filename = f"Downtime_History_{data['machine']}_{data['from_date']}_{data['to_date']}.csv"
            return send_file(csv_bytes, mimetype="text/csv; charset=utf-8", as_attachment=True, download_name=filename)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except StorageError:
            return jsonify({"error": "Downtime storage unavailable."}), 503
    return bp