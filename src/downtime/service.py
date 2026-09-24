import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
import pandas as pd

CSV_COLUMNS = [
    "Machine", "Type Downtime", "Detail", "EN Check In",
    "Timestamp Check In", "EN Check Out", "Timestamp Check Out",
    "Duration (hr)", "Status"
]
STORE_TIME_FORMAT = "%d/%m/%Y %H:%M"
API_TIME_FORMAT = "%Y-%m-%dT%H:%M"

class DowntimeError(Exception):
    pass

class ValidationError(DowntimeError):
    pass

class ConflictError(DowntimeError):
    pass

class StorageError(DowntimeError):
    pass

class DowntimeStore:
    def __init__(self, record_dir, type_dir):
        self.record_dir = Path(record_dir)
        self.type_dir = Path(type_dir)
        self._locks_guard = threading.Lock()
        self._machine_locks = {}
    def _machine_lock(self, machine):
        with self._locks_guard:
            if machine not in self._machine_locks:
                self._machine_locks[machine] = threading.RLock()
            return self._machine_locks[machine]
    def _require_type_dir(self):
        if not self.type_dir.exists():
            raise StorageError("Downtime type storage is unavailable.")
    def list_machines(self):
        self._require_type_dir()
        try:
            return sorted(file.stem for file in self.type_dir.glob("*.csv") if file.is_file())
        except OSError as e:
            raise StorageError("Unable to read machine list.") from e
    def validate_machine(self, machine):
        machine = str(machine or "").strip()
        if not machine:
            raise ValidationError("Machine is required.")
        if machine not in self.list_machines():
            raise ValidationError("Invalid machine.")
        return machine
    def get_downtime_types(self, machine):
        machine = self.validate_machine(machine)
        file_path = self.type_dir / f"{machine}.csv"
        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except Exception as e:
            raise StorageError("Unable to read downtime types.") from e
        df.columns = df.columns.astype(str).str.strip()
        if "Type Downtime" not in df.columns:
            raise StorageError("Invalid downtime type file.")
        if "Active" in df.columns:
            df = df[df["Active"].astype(str).str.strip() == "1"]
        return (
            df["Type Downtime"].astype(str).str.strip()
            .loc[lambda x: x != ""].tolist()
        )
    def _machine_file(self, machine):
        return self.record_dir / f"{machine}.csv"
    def _read_machine(self, machine):
        file_path = self._machine_file(machine)
        if not file_path.exists():
            return pd.DataFrame(columns=CSV_COLUMNS)
        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except Exception as e:
            raise StorageError("Unable to read downtime record.") from e
        df.columns = df.columns.astype(str).str.strip()
        missing = [c for c in CSV_COLUMNS if c not in df.columns]
        if missing:
            raise StorageError("Invalid downtime record format.")
        return df
    @staticmethod
    def _validate_en(value, name):
        value = str(value or "").strip()
        if not value:
            raise ValidationError(f"{name} is required.")
        if not value.isdigit():
            raise ValidationError(f"{name} must contain numbers only.")
        if len(value) > 20:
            raise ValidationError(f"{name} is too long.")
        return value
    @staticmethod
    def _validate_detail(detail):
        detail = str(detail or "").strip()
        if not detail:
            raise ValidationError("Detail is required.")
        if len(detail) > 300:
            raise ValidationError("Detail is too long.")
        if "\n" in detail or "\r" in detail:
            raise ValidationError("Detail must be one line.")
        return detail
    @staticmethod
    def _parse_api_time(value, field_name):
        try:
            return datetime.strptime(str(value or "").strip(), API_TIME_FORMAT)
        except ValueError as e:
            raise ValidationError(f"{field_name} is invalid.") from e
    @staticmethod
    def _atomic_write(df, file_path):
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError("Downtime storage unavailable.") from e
        temp_path = None
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{file_path.stem}.", suffix=".tmp", dir=str(file_path.parent)
            )
            os.close(fd)
            temp_path = Path(temp_name)
            df.to_csv(temp_path, index=False, encoding="utf-8-sig")
            os.replace(temp_path, file_path)
        except OSError as e:
            raise StorageError("Unable to save downtime record.") from e
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    def get_open_downtime(self, machine):
        machine = self.validate_machine(machine)
        df = self._read_machine(machine)
        if df.empty:
            return []
        mask = df["Status"].astype(str).str.strip().str.upper() == "OPENED"
        records = []
        for csv_index, row in df[mask].iterrows():
            checkin_text = str(row.get("Timestamp Check In", "")).strip()
            try:
                checkin_dt = datetime.strptime(checkin_text, STORE_TIME_FORMAT)
                checkin_iso = checkin_dt.strftime(API_TIME_FORMAT)
            except ValueError:
                checkin_iso = ""
            records.append({
                "row_index": int(csv_index),
                "machine": machine,
                "type": str(row.get("Type Downtime", "")),
                "detail": str(row.get("Detail", "")),
                "en_checkin": str(row.get("EN Check In", "")),
                "checkin": checkin_text,
                "checkin_iso": checkin_iso,
                "status": "OPENED"
            })
        return records
    def add_downtime(self, machine, downtime_type, detail, en_checkin, checkin_iso):
        machine = self.validate_machine(machine)
        downtime_type = str(downtime_type or "").strip()
        detail = self._validate_detail(detail)
        en_checkin = self._validate_en(en_checkin, "EN Check In")
        checkin_dt = self._parse_api_time(checkin_iso, "Check In Time")
        if downtime_type not in self.get_downtime_types(machine):
            raise ValidationError("Invalid or inactive Downtime Type.")
        checkin_text = checkin_dt.strftime(STORE_TIME_FORMAT)
        with self._machine_lock(machine):
            df = self._read_machine(machine)
            new_row = {
                "Machine": machine,
                "Type Downtime": downtime_type,
                "Detail": detail,
                "EN Check In": en_checkin,
                "Timestamp Check In": checkin_text,
                "EN Check Out": "",
                "Timestamp Check Out": "",
                "Duration (hr)": "",
                "Status": "OPENED"
            }
            df.loc[len(df)] = new_row
            self._atomic_write(df, self._machine_file(machine))
            row_index = len(df) - 1
        return {
            "row_index": row_index,
            "machine": machine,
            "type": downtime_type,
            "detail": detail,
            "en_checkin": en_checkin,
            "checkin": checkin_text,
            "checkin_iso": checkin_dt.strftime(API_TIME_FORMAT),
            "status": "OPENED"
        }
    def close_downtime(self, machine, items, en_checkout):
        machine = self.validate_machine(machine)
        en_checkout = self._validate_en(en_checkout, "EN Check Out")
        if not isinstance(items, list):
            raise ValidationError("Invalid request.")
        if not items:
            raise ValidationError("No downtime selected.")
        prepared = []
        used_indexes = set()
        for item in items:
            try:
                row_index = int(item.get("row_index"))
            except Exception:
                raise ValidationError("Invalid downtime row.")
            if row_index in used_indexes:
                raise ValidationError("Duplicate downtime row.")
            used_indexes.add(row_index)
            expected_checkin = str(item.get("checkin", "")).strip()
            try:
                checkin_dt = datetime.strptime(expected_checkin, STORE_TIME_FORMAT)
            except ValueError:
                raise ValidationError("Invalid Check In Time.")
            checkout_dt = self._parse_api_time(item.get("checkout"), "Check Out Time")
            if checkout_dt < checkin_dt:
                raise ValidationError("Check Out cannot be before Check In.")
            duration = round((checkout_dt - checkin_dt).total_seconds() / 3600, 2)
            prepared.append({
                "row_index": row_index,
                "expected_checkin": expected_checkin,
                "checkout": checkout_dt.strftime(STORE_TIME_FORMAT),
                "duration": duration
            })
        with self._machine_lock(machine):
            df = self._read_machine(machine)
            for update in prepared:
                row_index = update["row_index"]
                if row_index not in df.index:
                    raise ConflictError("Record changed. Refresh page.")
                status = str(df.at[row_index, "Status"]).strip().upper()
                current_checkin = str(df.at[row_index, "Timestamp Check In"]).strip()
                if status != "OPENED":
                    raise ConflictError("Record already closed.")
                if current_checkin != update["expected_checkin"]:
                    raise ConflictError("Record changed. Refresh page.")
            for update in prepared:
                row_index = update["row_index"]
                df.at[row_index, "EN Check Out"] = en_checkout
                df.at[row_index, "Timestamp Check Out"] = update["checkout"]
                df.at[row_index, "Duration (hr)"] = str(update["duration"])
                df.at[row_index, "Status"] = "CLOSED"
            self._atomic_write(df, self._machine_file(machine))
        return len(prepared)