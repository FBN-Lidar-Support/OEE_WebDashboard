"""Read yield counts and run time per machine from FITS.

Each config section (e.g. [AA_FAS_SAS]) is one machine group, with its OPNs in
line order in OPN_LIST. For every group this module returns how many units
started / finished / passed on each machine and how long each machine ran.

Run time of one SN
    END_DATETIME at the last OPN  -  START_DATETIME at the first OPN
    e.g. AA_FAS_SAS (IN460,IN490,IN500): START_DATETIME@IN460 -> END_DATETIME@IN500
    A group with one OPN (AB2B_POST_TEST: IN435) uses both times of that OPN.
    An SN that FAILED midway: START_DATETIME@first OPN -> END_DATETIME@FAIL OPN.

FITS calls used
    fn_Query_Table(opn, "PASS"/"FAIL", "Yield_SN")
        -> SN list of the day at one OPN (first yield)
    fn_Query(opn, sn, "STATION_NAME,START_DATETIME,END_DATETIME")
        -> station and times of one SN at one OPN
"""
import configparser
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import requests


# =============================================================================
# 1. SETTINGS
# =============================================================================
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.ini"

FITS_URL = os.getenv("FITS_URL", "https://service.fabrinet.co.th/FBNFITSService/FBNFITSServices.svc?wsdl")
PROJECT_ID = os.getenv("FITS_PROJECT_ID", "729")

# FITS field names (parameters of fn_Query)
FIELD_STATION = "STATION_NAME"
FIELD_START = "START_DATETIME"          # when the SN started the OPN
FIELD_END = "END_DATETIME"              # when the SN finished the OPN
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"       # e.g. "2026-02-18 08:03:47"

# A cycle longer than this many times the standard cycle (3600 / IDEAL_SPEED)
# is waiting / on hold: it is counted at the standard cycle time instead.
MAX_CYCLE_FACTOR = 3

# Process names used in main_daily.py that differ from the config section name
PROCESS_KEYS = {"IEOL_S": "IEOL_SHORT", "IEOL_L": "IEOL_LONG"}

FIELDS = ("input_first_opn", "total_last_opn", "pass_last_opn", "duration_hr")


# =============================================================================
# 2. FITS API
# =============================================================================
def _query(session, method, opn="-", serial="-", parameters=""):
    """Send one SOAP request to FITS and return the XML root."""
    user, password = os.getenv("FITS_USER"), os.getenv("FITS_PASSWORD")
    if not user or not password:
        raise RuntimeError("Set FITS_USER and FITS_PASSWORD in Windows Environment Variables")
    values = {
        "project_id":    PROJECT_ID,
        "user_name":     user,
        "user_password": password,
        "model":         "Main line",
        "operation":     opn,
        "revision":      "2.9",
        "serial":        serial,
        "parameters":    parameters,
        "fsp":           ",",
    }
    fields = "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in values.items())
    soap = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<s:Body><{method} xmlns="http://tempuri.org/">{fields}</{method}></s:Body>'
        '</s:Envelope>'
    ).encode("utf-8")
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"http://tempuri.org/IFBNFITSServices/{method}"',
    }
    for attempt in range(3):
        try:
            response = session.post(FITS_URL, headers=headers, data=soap, timeout=(5, 30))
            response.raise_for_status()
            root = ET.fromstring(response.content)
            fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
            if fault is not None:
                message = fault.findtext("faultstring", default="Unknown SOAP fault")
                raise RuntimeError(f"FITS {method}: {message}")
            return root
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.HTTPError, ET.ParseError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if (status is not None and status < 500) or attempt == 2:
                raise
            print(f"FITS retry {attempt + 1}/3: {type(exc).__name__}")
            time.sleep(attempt + 1)


def _tag(node):
    return node.tag.rsplit("}", 1)[-1]


def get_serials(session, opn, result):
    """SN list of the day at one OPN. result = "PASS" or "FAIL"."""
    root = _query(session, "fn_Query_Table", opn, result, "Yield_SN")
    serials = set()
    for row in root.iter():
        if _tag(row) != "RESULT":
            continue
        for field in row:
            if _tag(field) == "serial_no" and field.text:
                serials.add(field.text.strip())
    return serials


def get_sn_fields(session, opn, sn, fields):
    """Read fields of one SN at one OPN.

    FITS answers with a text like
        "1_STATION_NAME : FBN_AA01, 1_DATE_TIME : Nov 16 2026 1:33PM"
    Returns {"STATION_NAME": "FBN_AA01", "DATE_TIME": "Nov 16 2026 1:33PM"}.
    """
    root = _query(session, "fn_Query", opn, sn, ",".join(fields))
    message = " ".join((node.text or "") for node in root.iter() if _tag(node) == "Message")
    values = {}
    for name, value in re.findall(r"(?:\d+_)?([A-Za-z_]+)\s*:\s*([^,;\r\n]*)", message):
        values.setdefault(name.upper(), value.strip())
    return {field: values.get(field.upper()) or None for field in fields}


def parse_time(text):
    """"2026-02-18 08:03:47" -> datetime, or None if empty / not a time."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), TIME_FORMAT)
    except ValueError:
        return None


# =============================================================================
# 3. READ ONE OPN
# =============================================================================
def read_opn(session, opn, fields, results=("PASS", "FAIL")):
    """All SNs of the day at one OPN, with the requested FITS fields.

    Returns {sn: {"result", "station_name", "start", "end", "reason"}}
      result     : PASS / FAIL / RETEST (in both PASS and FAIL lists)
      start, end : datetime of START_DATETIME / END_DATETIME (None if not asked / empty)
      reason     : list of data problems of this SN (empty = OK)
    """
    lists = {result: get_serials(session, opn, result) for result in results}
    passed, failed = lists.get("PASS", set()), lists.get("FAIL", set())
    records = {}
    for sn in sorted(passed | failed):
        result = "RETEST" if sn in passed and sn in failed else "PASS" if sn in passed else "FAIL"
        record = {"result": result, "station_name": None, "start": None, "end": None, "reason": []}
        try:
            values = get_sn_fields(session, opn, sn, fields)
        except (requests.exceptions.RequestException, ET.ParseError):
            record["reason"].append("QUERY_FAILED")
            records[sn] = record
            continue
        station = values.get(FIELD_STATION)
        record["station_name"] = station.upper() if station else None
        if not station:
            record["reason"].append("STATION_NAME")
        record["start"] = parse_time(values.get(FIELD_START))
        record["end"] = parse_time(values.get(FIELD_END))
        records[sn] = record
    return records


def get_start_time(session, opn, sn, cache):
    """START_DATETIME of one SN at the first OPN (any day, so cross-day work is found)."""
    key = (opn, sn)
    if key not in cache:
        try:
            cache[key] = parse_time(get_sn_fields(session, opn, sn, [FIELD_START])[FIELD_START])
        except (requests.exceptions.RequestException, ET.ParseError, RuntimeError):
            cache[key] = None
    return cache[key]


# =============================================================================
# 4. CONFIG
# =============================================================================
def read_group(config, section):
    """Settings of one machine group (config section)."""
    if not config.has_section(section):
        raise ValueError(f"Missing config section [{section}]")
    opns = [v.strip() for v in config.get(section, "OPN_LIST").split(",") if v.strip()]
    if not opns or any(";" in opn for opn in opns):
        raise ValueError(f"Invalid OPN_LIST in [{section}]; use commas")
    stations = {
        key.upper(): value.strip()
        for key, value in config.items(section)
        if key.upper().startswith(("FBN_", "HVM_"))
    }
    if not stations or any(not machine for machine in stations.values()):
        raise ValueError(f"Missing/empty station mapping in [{section}]")
    try:
        speed = float(config.get(section, "IDEAL_SPEED", fallback="0"))
    except ValueError:
        speed = 0.0
    return {
        "opns": opns,                                        # in line order
        "stations": stations,                                # FITS station -> machine
        "ideal_speed": speed,                                # cycles per hour
    }


# =============================================================================
# 5. RESULT HELPERS
# =============================================================================
def _empty():
    return dict.fromkeys(FIELDS, 0)


def _new_result(group):
    machines = dict.fromkeys(group["stations"].values())
    return {
        **_empty(),
        "machines": {name: {**_empty(), "cycles_timed": 0, "cycles_excluded": 0, "failed_midway": 0}
                     for name in machines},
        "uncount": {},          # {opn: {sn: record + reason}} SNs with data problems
        "retest_count": 0,
        "data_quality_ok": True,
    }


def _flag(data, opn, sn, record, reasons, excluded):
    """Remember an SN with a data problem; the group becomes DATA INCOMPLETE."""
    data["uncount"].setdefault(opn, {})[sn] = {
        **record,
        "start": str(record["start"]) if record.get("start") else None,
        "end": str(record["end"]) if record.get("end") else None,
        "reason": reasons,
        "excluded_from_machine_yield": excluded,
        "result_unresolved": record["result"] == "RETEST",
    }
    data["data_quality_ok"] = False


def _machine_of(data, group, opn, sn, record):
    """Machine of one SN, or None (SN is flagged if its station is unknown)."""
    machine = group["stations"].get(record["station_name"])
    reasons = record["reason"].copy()
    if record["station_name"] and machine is None:
        reasons.append("UNMAPPED_STATION")
    if reasons:
        _flag(data, opn, sn, record, reasons, excluded=machine is None)
    return machine


def _add_count(data, machine, field, amount=1):
    data[field] += amount
    if machine is not None:
        data["machines"][machine][field] += amount


def _merged_hours(intervals):
    """Total hours of (start, end) intervals; overlapping parts count once."""
    total, current = 0.0, None
    for start, end in sorted(intervals):
        if current and start <= current[1]:
            current[1] = max(current[1], end)
            continue
        if current:
            total += (current[1] - current[0]).total_seconds()
        current = [start, end]
    if current:
        total += (current[1] - current[0]).total_seconds()
    return total / 3600


def _round_durations(data):
    for values in data["machines"].values():
        values["duration_hr"] = round(values["duration_hr"], 6)
    data["duration_hr"] = round(sum(v["duration_hr"] for v in data["machines"].values()), 6)


# =============================================================================
# 6. ONE MACHINE GROUP
# =============================================================================
def read_group_yield(session, group, cache, start_cache):
    """Counts and run time of one machine group.

    Step 1  First OPN : SN list + START/END time  -> Cycles Started
    Step 2  Last OPN  : SN list + END time        -> Cycles / Passed, end time
    Step 3  Other OPNs: FAIL list only            -> SNs that failed midway
    Step 4  Run time per machine = sum of (end - start) of every SN
    """
    data = _new_result(group)
    opns = group["opns"]
    first_opn, last_opn = opns[0], opns[-1]
    standard_sec = 3600 / group["ideal_speed"] if group["ideal_speed"] > 0 else None
    intervals = {name: [] for name in data["machines"]}
    retests = set()

    def read(opn, fields, results=("PASS", "FAIL")):
        key = (opn, tuple(fields), results)
        if key not in cache:
            cache[key] = read_opn(session, opn, fields, results)
        return cache[key]

    # Step 1: first OPN -> Cycles Started (START time is kept for step 4)
    first_records = read(first_opn, [FIELD_STATION, FIELD_START, FIELD_END])
    for sn, record in first_records.items():
        if record["result"] == "RETEST":
            retests.add(sn)
        machine = _machine_of(data, group, first_opn, sn, record)
        _add_count(data, machine, "input_first_opn")

    def start_of(sn):
        """START_DATETIME at the first OPN; asked per SN if it started on another day."""
        if sn in first_records and first_records[sn]["start"]:
            return first_records[sn]["start"]
        return get_start_time(session, first_opn, sn, start_cache)

    def add_run_time(opn, sn, record, machine):
        """Add the run time of one SN to its machine (or flag why it can't)."""
        end = record["end"]
        start = start_of(sn) if end else None
        if end is None:
            return _flag(data, opn, sn, record, ["NO_END_TIME"], excluded=False)
        if start is None:
            return _flag(data, opn, sn, record, ["NO_START_TIME"], excluded=False)
        if end < start:
            return _flag(data, opn, sn, record, ["INVALID_CYCLE_TIME"], excluded=False)
        values = data["machines"][machine]
        if standard_sec and (end - start).total_seconds() > MAX_CYCLE_FACTOR * standard_sec:
            values["cycles_excluded"] += 1      # waiting / on hold
            return
        values["cycles_timed"] += 1
        intervals[machine].append((start, end))

    # Step 2: last OPN -> Cycles / Passed + run time of finished SNs
    # (SNs that started but have not finished yet are simply not in this list)
    if last_opn == first_opn:
        last_records = first_records
    else:
        last_records = read(last_opn, [FIELD_STATION, FIELD_END])
    for sn, record in last_records.items():
        if record["result"] == "RETEST":
            retests.add(sn)
        machine = _machine_of(data, group, last_opn, sn, record)
        passed = record["result"] in ("PASS", "RETEST")
        _add_count(data, machine, "total_last_opn")
        _add_count(data, machine, "pass_last_opn", int(passed))
        if machine is not None:
            add_run_time(last_opn, sn, record, machine)

    # Step 3: SNs that FAILED before the last OPN. They never reach it, but the
    # machine ran them: one cycle that did not pass, run time up to the FAIL.
    # The OPN where an SN is in the FAIL list is where it failed (line order).
    done = set(last_records)
    for opn in opns[:-1]:
        if opn == first_opn:
            fails = {sn: r for sn, r in first_records.items() if r["result"] == "FAIL"}
        else:
            fails = read(opn, [FIELD_STATION, FIELD_END], results=("FAIL",))
        for sn, record in fails.items():
            if sn in done:
                continue
            done.add(sn)
            machine = _machine_of(data, group, opn, sn, record)
            _add_count(data, machine, "total_last_opn")
            if machine is not None:
                data["machines"][machine]["failed_midway"] += 1
                add_run_time(opn, sn, record, machine)

    # Step 4: run time per machine. One SN at a time per machine, so
    # overlapping intervals are merged (never added twice). A cycle that was
    # too long counts at the standard cycle time.
    standard_hr = standard_sec / 3600 if standard_sec else 0.0
    for machine, values in data["machines"].items():
        values["duration_hr"] = _merged_hours(intervals[machine]) + values["cycles_excluded"] * standard_hr
    data["retest_count"] = len(retests)
    _round_durations(data)
    return data


# =============================================================================
# 7. MAIN
# =============================================================================
def get_yield_yesterday(MC_DICT, config_path=CONFIG_PATH):
    """Yield counts and run time of every group in MC_DICT.

    Returns {process: {input_first_opn, total_last_opn, pass_last_opn,
                       duration_hr, machines: {machine: {...}}, uncount,
                       retest_count, data_quality_ok}}
    """
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(config_path, encoding="utf-8-sig"):
        raise FileNotFoundError(f"Cannot read config: {config_path}")
    output, cache, start_cache = {}, {}, {}
    with requests.Session() as session:
        for process in MC_DICT:
            group = read_group(config, PROCESS_KEYS.get(process, process))
            output[process] = read_group_yield(session, group, cache, start_cache)
    return output

