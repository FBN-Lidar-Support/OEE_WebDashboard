"""Read FITS Yield and Duration per process and physical machine."""
import configparser
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape
import requests
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.ini"
FITS_URL = os.getenv("FITS_URL", "https://service.fabrinet.co.th/FBNFITSService/FBNFITSServices.svc?wsdl")
PROJECT_ID = os.getenv("FITS_PROJECT_ID", "729")
PROCESS_KEYS = {"IEOL_S": "IEOL_SHORT", "IEOL_L": "IEOL_LONG"}
FIELDS = ("input_first_opn", "total_last_opn", "pass_last_opn", "duration_hr")

# 1. FITS API
def _query(session, method, opn="-", serial="-", parameters=""):
    """Send SOAP request and return XML."""
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
        "fsp":           ","
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
        "SOAPAction": f'"http://tempuri.org/IFBNFITSServices/{method}"'
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
# 2. GET SN + STATION + DURATION
def _serials(session, opn, result):
    """Get unique SNs for PASS or FAIL."""
    root = _query(session, "fn_Query_Table", opn, result, "Yield_SN")
    serials = set()
    for row in root.iter():
        if row.tag.rsplit("}", 1)[-1] != "RESULT":
            continue
        for field in row:
            if field.tag.rsplit("}", 1)[-1] == "serial_no" and field.text:
                serials.add(field.text.strip())
    return serials
def _opn_records(session, opn):
    """Get SN details; missing data and retests are tracked."""
    passed, failed = _serials(session, opn, "PASS"), _serials(session, opn, "FAIL")
    records = {}
    for sn in sorted(passed | failed):
        result = "RETEST" if sn in passed and sn in failed else "PASS" if sn in passed else "FAIL"
        try:
            root = _query(session, "fn_Query", opn, sn, "STATION_NAME,DURATION")
        except (requests.exceptions.RequestException, ET.ParseError):
            records[sn] = {"result": result, "station_name": None, "duration_hr": 0.0, "reason": ["QUERY_FAILED"]}
            continue
        message = " ".join((node.text or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "Message")
        station_match = re.search(r"(?:\d+_)?STATION_NAME\s*:\s*([^,;\r\n]+)", message, re.I)
        duration_match = re.search(r"(?:\d+_)?DURATION\s*:\s*(-?\d+(?:\.\d+)?)", message, re.I)
        station = station_match.group(1).strip().upper() if station_match else None
        seconds = float(duration_match.group(1)) if duration_match else None
        issues = []

        if not station:
            issues.append("STATION_NAME")
        if seconds is None:
            issues.append("DURATION")
        elif not math.isfinite(seconds) or seconds < 0:
            issues.append("INVALID_DURATION")
            seconds = None
        records[sn] = {
            "result": result,
            "station_name": station,
            "duration_hr": seconds / 3600 if seconds is not None else 0.0,
            "reason": issues
        }
    return records
# 3. CONFIG
def _settings(config, section):
    """Read OPN list and station-to-machine mapping."""
    if not config.has_section(section):
        raise ValueError(f"Missing config section [{section}]")
    opns = [v.strip() for v in config.get(section, "OPN_LIST").split(",") if v.strip()]
    if not opns or any(";" in opn for opn in opns):
        raise ValueError(f"Invalid OPN_LIST in [{section}]; use commas")
    mapping = {
        key.upper(): value.strip()
        for key, value in config.items(section)
        if key.upper().startswith(("FBN_", "HVM_"))
    }
    if not mapping or any(not machine for machine in mapping.values()):
        raise ValueError(f"Missing/empty station mapping in [{section}]")
    return opns, mapping
def _empty():
    return dict.fromkeys(FIELDS, 0)

# 4. MAIN YIELD CALCULATION
def get_yield_yesterday(MC_DICT, config_path=CONFIG_PATH):
    """Return process totals, machine totals and uncount SNs."""
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(config_path, encoding="utf-8-sig"):
        raise FileNotFoundError(f"Cannot read config: {config_path}")
    output, cache = {}, {}
    with requests.Session() as session:
        for process in MC_DICT:
            opns, mapping = _settings(config, PROCESS_KEYS.get(process, process))
            data = _empty()
            data.update(
                machines={name: _empty() for name in dict.fromkeys(mapping.values())},
                uncount={},
                retest_count=0,
                data_quality_ok=True
            )
            retest_seen = set()
            for index, opn in enumerate(opns):
                if opn not in cache:
                    # print(f"FITS Yield: querying {opn}")
                    cache[opn] = _opn_records(session, opn)
                first, last = index == 0, index == len(opns) - 1
                for sn, record in cache[opn].items():
                    machine = mapping.get(record["station_name"])
                    passed = record["result"] in ("PASS", "RETEST")
                    # Process-level yield
                    if first:
                        data["input_first_opn"] += 1
                    if last:
                        data["total_last_opn"] += 1
                        data["pass_last_opn"] += int(passed)
                    if record["result"] == "RETEST":
                        retest_seen.add(sn)
                    # Track incomplete / conflicting data
                    issues = record["reason"].copy()
                    if record["station_name"] and machine is None:
                        issues.append("UNMAPPED_STATION")
                    if issues:
                        data["uncount"].setdefault(opn, {})[sn] = {
                            **record,
                            "reason": issues,
                            "excluded_from_machine_yield": machine is None,
                            "result_unresolved": record["result"] == "RETEST"
                        }
                        data["data_quality_ok"] = False
                    if machine is None:
                        continue
                    # Machine-level yield and active duration
                    values = data["machines"][machine]
                    if first:
                        values["input_first_opn"] += 1
                    if last:
                        values["total_last_opn"] += 1
                        values["pass_last_opn"] += int(passed)
                    values["duration_hr"] += record["duration_hr"]
                    data["duration_hr"] += record["duration_hr"]
            data["retest_count"] = len(retest_seen)
            data["duration_hr"] = round(data["duration_hr"], 6)
            for values in data["machines"].values():
                values["duration_hr"] = round(values["duration_hr"], 6)
            output[process] = data
    return output