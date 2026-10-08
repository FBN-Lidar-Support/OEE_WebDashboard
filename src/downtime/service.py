import os
import tempfile
import threading
from datetime import datetime, timedelta
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
        if not self.type_dir.exists() or not self.type_dir.is_dir():
            raise StorageError("Downtime type storage is unavailable.")
    def list_lines(self):
        self._require_type_dir()
        try:
            return sorted(folder.name for folder in self.type_dir.iterdir() if folder.is_dir() and not folder.name.startswith("."))
        except OSError as e:
            raise StorageError("Unable to read line list.") from e
    def validate_line(self, line):
        line = str(line or "").strip()
        if not line:
            raise ValidationError("Line is required.")
        if line not in self.list_lines():
            raise ValidationError("Invalid line.")
        return line
    def list_machines(self, line):
        line = self.validate_line(line)
        line_dir = self.type_dir / line
        try:
            return sorted(file.stem for file in line_dir.glob("*.csv") if file.is_file())
        except OSError as e:
            raise StorageError("Unable to read machine list.") from e
    def _find_machine_line(self, machine):
        machine = str(machine or "").strip()
        if not machine:
            raise ValidationError("Machine is required.")
        found = []
        for line in self.list_lines():
            if machine in self.list_machines(line):
                found.append(line)
        if not found:
            raise ValidationError("Invalid machine.")
        if len(found) > 1:
            raise ValidationError("Machine exists in more than one line.")
        return found[0]
    def validate_machine(self, machine, line=None):
        machine = str(machine or "").strip()
        if not machine:
            raise ValidationError("Machine is required.")
        if line is None:
            self._find_machine_line(machine)
            return machine
        line = self.validate_line(line)
        if machine not in self.list_machines(line):
            raise ValidationError("Invalid machine for selected line.")
        return machine
    def get_downtime_types(self, line, machine):
        line = self.validate_line(line)
        machine = self.validate_machine(machine, line)
        file_path = self.type_dir / line / f"{machine}.csv"
        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except Exception as e:
            raise StorageError("Unable to read downtime types.") from e
        df.columns = df.columns.astype(str).str.strip()
        if "Type Downtime" not in df.columns:
            raise StorageError("Invalid downtime type file.")
        if "Active" in df.columns:
            df = df[df["Active"].astype(str).str.strip() == "1"]
        return df["Type Downtime"].astype(str).str.strip().loc[lambda x: x != ""].tolist()
    def _machine_file(self, machine):
        line = self._find_machine_line(machine)
        return self.record_dir / line / f"{machine}.csv"
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
            fd, temp_name = tempfile.mkstemp(prefix=f".{file_path.stem}.", suffix=".tmp", dir=str(file_path.parent))
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
    def add_downtime(self, line, machine, downtime_type, detail, en_checkin, checkin_iso):
        line = self.validate_line(line)
        machine = self.validate_machine(machine, line)
        downtime_type = str(downtime_type or "").strip()
        detail = self._validate_detail(detail)
        en_checkin = self._validate_en(en_checkin, "EN Check In")
        checkin_dt = self._parse_api_time(checkin_iso, "Check In Time")
        if downtime_type not in self.get_downtime_types(line, machine):
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
    @staticmethod
    def _history_date(value, field):
        try:
            return datetime.strptime(str(value or "").strip(), "%Y-%m-%d")
        except ValueError as e:
            raise ValidationError(f"Invalid {field}. Use YYYY-MM-DD.") from e
    def get_downtime_history(self, line, machine, from_date, to_date):
        line = self.validate_line(line)
        machine = self.validate_machine(machine, line)
        first = self._history_date(from_date, "From Date")
        last = self._history_date(to_date, "To Date")
        if last < first:
            raise ValidationError("To Date cannot be before From Date.")
        if (last - first).days > 366:
            raise ValidationError("Date range cannot exceed 367 days.")
        start = first + timedelta(hours=7)
        end = last + timedelta(days=1, hours=7)
        now = datetime.now()
        with self._machine_lock(machine):
            df = self._read_machine(machine).copy()
        records = []
        intervals = []
        type_hours, type_events = {}, {}
        daily = {
            (first + timedelta(days=i)).date().isoformat(): 0.0
            for i in range((last - first).days + 1)
        }
        for _, row in df.iterrows():
            record = {col: str(row[col]) for col in CSV_COLUMNS}
            try:
                checkin = datetime.strptime(record["Timestamp Check In"].strip(), STORE_TIME_FORMAT)
            except ValueError:
                continue
            status = record["Status"].strip().upper()
            if status == "CLOSED":
                try:
                    effective_end = datetime.strptime(record["Timestamp Check Out"].strip(), STORE_TIME_FORMAT)
                except ValueError:
                    continue
            elif status == "OPENED":
                effective_end = now
            else:
                continue
            if effective_end <= checkin:
                continue
            clip_start = max(checkin, start)
            clip_end = min(effective_end, end)
            if clip_end <= clip_start:
                continue
            downtime_type = record["Type Downtime"].strip() or "(Unspecified)"
            hours = (clip_end - clip_start).total_seconds() / 3600
            records.append((checkin, record))
            intervals.append((clip_start, clip_end))
            # Ranking: count each event's actual duration, including overlaps.
            type_hours[downtime_type] = type_hours.get(downtime_type, 0.0) + hours
            type_events[downtime_type] = type_events.get(downtime_type, 0) + 1
        # Total Downtime: merge overlapping intervals, matching OEE.
        intervals.sort(key=lambda x: x[0])
        merged = []
        for interval_start, interval_end in intervals:
            if merged and interval_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
            else:
                merged.append((interval_start, interval_end))
        total_seconds = sum((b - a).total_seconds() for a, b in merged)
        total_hours = total_seconds / 3600
        # Daily Trend: split unique downtime by production day.
        for interval_start, interval_end in merged:
            cursor = interval_start
            while cursor < interval_end:
                production_day = (cursor - timedelta(hours=7)).date()
                next_boundary = datetime.combine(
                    production_day + timedelta(days=1), datetime.min.time()
                ) + timedelta(hours=7)
                segment_end = min(interval_end, next_boundary)
                daily[production_day.isoformat()] += (segment_end - cursor).total_seconds() / 3600
                cursor = segment_end
        ranking = sorted(type_hours, key=lambda t: (-type_hours[t], t.casefold()))
        ranking_data = [
            {
                "type": t,
                "hours": round(type_hours[t], 4),
                "events": type_events[t]
            }
            for t in ranking
        ]
        trend_data = [{"date": day, "hours": round(hours, 4)} for day, hours in daily.items()]
        records.sort(key=lambda item: item[0], reverse=True)
        return {
            "line": line,
            "machine": machine,
            "from_date": first.date().isoformat(),
            "to_date": last.date().isoformat(),
            "summary": {
                "total_downtime_hr": round(total_hours, 4),
                "total_events": len(records),
                "top_downtime_type": ranking_data[0]["type"] if ranking_data else None
            },
            "trend": trend_data,
            "ranking": ranking_data,
            "columns": CSV_COLUMNS,
            "records": [record for _, record in records]
        }