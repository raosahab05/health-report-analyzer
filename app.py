from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from datetime import datetime
import pytesseract
from PIL import Image, ImageOps
from daily_plan import build_daily_diet, build_daily_precautions
import pymupdf as fitz  # PyMuPDF for converting scanned PDFs to images
import os
import json
import re
import uuid
import hashlib


app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "health-care-project-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload size

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ============================================================
# TESSERACT
# ============================================================

if os.name == "nt":
    tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path


# ============================================================
# ANALYSIS STORAGE
# ============================================================

analysis_store = {}

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "report_history.json"
)


def load_report_history():
    try:
        if not os.path.exists(HISTORY_FILE):
            return []

        with open(HISTORY_FILE, "r", encoding="utf-8") as history_file:
            data = json.load(history_file)

        return data if isinstance(data, list) else []

    except (OSError, json.JSONDecodeError):
        return []


def save_report_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as history_file:
            json.dump(history, history_file, indent=2, ensure_ascii=False)

    except OSError as error:
        print("Report History Save Error:", error)


report_history = load_report_history()


def get_analysis_data(analysis_id):
    """Retrieve analysis data from RAM or fall back to persisted history."""
    if not analysis_id:
        return None

    if analysis_id in analysis_store:
        return analysis_store[analysis_id]

    for entry in reversed(report_history):
        if entry.get("report_id") == analysis_id:
            params = entry.get("parameters", {})
            return {
                "report_name": entry.get("report_name", "Uploaded Report"),
                "analysis_date": entry.get("analysis_date", "Not Available"),
                "report_type": entry.get("report_type", "Laboratory Report"),
                "test_name": entry.get("test_name", "Not Available"),
                "test_result": entry.get("test_result", "Not Applicable"),
                "patient_info": entry.get("patient_info", {
                    "age": "Not Available",
                    "gender": "Not Available",
                    "report_status": "Not Available",
                    "report_date": entry.get("report_date", "Not Available")
                }),
                "report_date": entry.get("report_date", "Not Available"),
                "parameters": params,
                "parameter_analysis": params,
                "qualitative_results": entry.get("qualitative_results", []),
                "findings": create_findings(params),
                "result_summary": create_result_summary(
                    entry.get("report_type", "Laboratory Report"),
                    entry.get("test_name", "Not Available"),
                    entry.get("test_result", "Not Applicable"),
                    params,
                    entry.get("qualitative_results", [])
                )
            }

    return None


# ============================================================
# REPORT HISTORY DATE HELPERS
# ============================================================

def parse_report_datetime(value):
    if not value:
        return None

    formats = [
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y %I:%M %p",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
    ]

    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue

    return None


def format_report_date(value):
    parsed = parse_report_datetime(value)

    if parsed:
        return parsed.strftime("%d %b %Y")

    return "Date Not Available"


def status_css_class(status):
    value = str(status or "Not Available").strip().lower()

    if value == "normal":
        return "normal"

    if value in ["low", "high", "monitor", "attention"]:
        return "monitor"

    return "normal"


# ============================================================
# NUMBER HELPERS
# ============================================================

def number_from_text(value):
    if value is None:
        return None

    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", str(value))

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def all_numbers(value):
    if value is None:
        return []

    return [
        float(item)
        for item in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", str(value))
    ]


# ============================================================
# STATUS
# ============================================================

def calculate_status(value, minimum=None, maximum=None):
    if value is None:
        return "Not Available"

    if minimum is not None and value < minimum:
        return "Low"

    if maximum is not None and value > maximum:
        return "High"

    return "Normal"


# ============================================================
# ADD PARAMETER
# ============================================================

def add_parameter(
    result,
    name,
    value,
    unit,
    reference_range,
    minimum=None,
    maximum=None,
    status=None,
    display_value=None
):
    numeric_value = number_from_text(value)

    if numeric_value is None:
        return

    if status is None:
        status = calculate_status(numeric_value, minimum, maximum)

    result[name] = {
        "value": display_value if display_value is not None else numeric_value,
        "numeric_value": numeric_value,
        "unit": unit,
        "reference_range": reference_range,
        "status": status
    }


# ============================================================
# NORMALIZE REPORT LINES
# ============================================================

def normalize_lines(text):
    text = text.replace("\xa0", " ")
    text = text.replace("–", "-")
    text = text.replace("−", "-")

    lines = []

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if line:
            lines.append(line)

    return lines


# ============================================================
# STRUCTURED CBC ROW
# ============================================================

def _parse_structured_cbc_row(line):
    match = re.match(
        r"^(?P<label>.+?)\s+"
        r"(?P<value><\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
        r"(?:(?P<flag>[HL])\s+)?"
        r"\(?(?P<low>\d+(?:\.\d+)?)\s*-\s*"
        r"(?P<high>\d+(?:\.\d+)?)\)?\s+"
        r"(?P<unit>.+?)\s*$",
        line,
        re.IGNORECASE
    )

    if not match:
        return None

    raw_value = match.group("value").replace(" ", "")
    numeric = number_from_text(raw_value)

    if numeric is None:
        return None

    return {
        "label": match.group("label").strip(),
        "raw_value": raw_value,
        "value": numeric,
        "flag": (match.group("flag") or "").upper(),
        "low": float(match.group("low")),
        "high": float(match.group("high")),
        "unit": match.group("unit").strip()
    }


# ============================================================
# CBC TABLE EXTRACTION
# ============================================================

def _extract_cbc_table_parameters(parameters, lines):
    cbc_map = {
        # Hemoglobin
        "haemoglobin": ("Hemoglobin", "g/dL"),
        "hemoglobin": ("Hemoglobin", "g/dL"),
        "hb": ("Hemoglobin", "g/dL"),

        # WBC
        "total leucocyte count": ("WBC Count", "/cumm"),
        "total leukocyte count": ("WBC Count", "/cumm"),
        "total wbc count": ("WBC Count", "/cumm"),
        "tlc": ("WBC Count", "/cumm"),

        # Differential count
        "neutrophils": ("Neutrophils", "%"),
        "polymorphs": ("Neutrophils", "%"),
        "lymphocytes": ("Lymphocytes", "%"),
        "eosinophils": ("Eosinophils", "%"),
        "monocytes": ("Monocytes", "%"),
        "basophils": ("Basophils", "%"),

        # Absolute counts
        "absolute neutrophils": ("Absolute Neutrophil Count", "/cumm"),
        "absolute lymphocytes": ("Absolute Lymphocyte Count", "/cumm"),
        "absolute eosinophils": ("Absolute Eosinophil Count", "/cumm"),
        "absolute monocytes": ("Absolute Monocyte Count", "/cumm"),
        "absolute basophils": ("Absolute Basophil Count", "/cumm"),

        # RBC and Hematocrit
        "rbc count": ("RBC Count", "Million/cumm"),
        "total rbc count": ("RBC Count", "Million/cumm"),
        "hct": ("Hematocrit", "%"),
        "hematocrit": ("Hematocrit", "%"),
        "pcv": ("Hematocrit", "%"),
        "p.c.v": ("Hematocrit", "%"),
        "packed cell volume": ("Hematocrit", "%"),

        # RBC indices
        "mcv": ("MCV", "fL"),
        "mean corpuscular volume": ("MCV", "fL"),
        "mean cell volume": ("MCV", "fL"),
        "mch": ("MCH", "pg"),
        "mean corpuscular hemoglobin": ("MCH", "pg"),
        "mchc": ("MCHC", "g/dL"),
        "mean corpuscular hemoglobin concentration": ("MCHC", "g/dL"),
        "rdw-cv": ("RDW CV", "%"),
        "rdw cv": ("RDW CV", "%"),
        "rdw-sd": ("RDW SD", "fL"),

        # Platelets
        "platelet count": ("Platelet Count", "/cumm"),
        "pct": ("PCT", "%"),
        "mpv": ("MPV", "fL"),
        "pdw": ("PDW", "fL"),
        "p-lcr": ("P-LCR", "%"),
        "p-lcc": ("P-LCC", "10^3/uL")
    }

    found = set()

    for line in lines:
        parsed = _parse_structured_cbc_row(line)

        if not parsed:
            continue

        clean_label = re.sub(r"\(.*?\)", "", parsed["label"]).strip().lower()
        key = re.sub(r"\s+", " ", clean_label)

        if key not in cbc_map:
            continue

        name, fallback_unit = cbc_map[key]

        minimum = parsed["low"]
        maximum = parsed["high"]

        parsed_value = parsed["value"]
        display_value = parsed["raw_value"]

        if (
            name == "Platelet Count"
            and 0 < parsed_value < 1000
            and minimum >= 100000
            and maximum >= 100000
            and parsed["unit"].strip().lower() in {"/cumm", "/cmm"}
        ):
            parsed_value *= 100000
            display_value = f"{parsed['raw_value']} x 10^5"

        flag = parsed["flag"]

        if flag == "H":
            status = "High"
        elif flag == "L":
            status = "Low"
        else:
            status = calculate_status(parsed_value, minimum, maximum)

        add_parameter(
            parameters,
            name,
            parsed_value,
            parsed["unit"] or fallback_unit,
            f"{minimum:g} - {maximum:g}",
            minimum,
            maximum,
            status=status,
            display_value=display_value
        )

        found.add(name)

    return found


# ============================================================
# SAFE LINE PARAMETER EXTRACTION
# ============================================================

def _add_line_parameter(
    parameters,
    lines,
    name,
    label_pattern,
    unit,
    reference_range,
    minimum=None,
    maximum=None
):
    if name in parameters:
        return False

    try:
        label_re = re.compile(label_pattern, re.IGNORECASE)
    except re.error:
        return False

    for line in lines:
        label_match = label_re.search(line)
        if not label_match:
            continue

        tail = line[label_match.end():]

        chosen_val = None
        for num_match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", tail):
            after = tail[num_match.end():].lstrip()
            before = tail[:num_match.start()].rstrip()
            if after.startswith("-") or before.endswith("-"):
                continue

            val = float(num_match.group(1))
            if maximum is not None and val > maximum * 20:
                continue

            chosen_val = val
            break

        if chosen_val is None:
            continue

        range_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(?!\d)", tail)
        row_low, row_high, row_ref = minimum, maximum, reference_range

        if range_match:
            a, b = float(range_match.group(1)), float(range_match.group(2))
            if a < b:
                row_low, row_high = a, b
                row_ref = f"{a:g} - {b:g}"

        add_parameter(
            parameters,
            name,
            chosen_val,
            unit,
            row_ref,
            row_low,
            row_high
        )
        return True

    return False


# ============================================================
# REGEX PARAMETER
# ============================================================

def _add_regex_parameter(
    parameters,
    text,
    name,
    pattern,
    unit,
    reference_range,
    minimum=None,
    maximum=None,
    status=None,
    display_value=None
):
    if name in parameters:
        return False

    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

    if not match:
        return False

    value = match.group("value")

    add_parameter(
        parameters,
        name,
        value,
        unit,
        reference_range,
        minimum,
        maximum,
        status=status,
        display_value=display_value
    )

    return True


# ============================================================
# KFT / KIDNEY FUNCTION TEST EXTRACTION
# ============================================================

def _kft_reference_from_text(row):
    match = re.search(r"(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)", row)

    if not match:
        return None

    low_raw = match.group("low")
    high_raw = match.group("high")

    low = float(low_raw)
    high = float(high_raw)

    if low < high:
        return (low, high, f"{low_raw} - {high_raw}")

    return None


def _kft_repair_reference_range(low_raw, high_raw, fallback_min, fallback_max):
    low = float(low_raw)
    high = float(high_raw)

    for div in (10, 100):
        rep_high = high / div
        if (
            low < rep_high
            and abs(low - fallback_min) <= fallback_max
            and abs(rep_high - fallback_max) <= fallback_max * 0.5
        ):
            return (low, rep_high, f"{low:g} - {rep_high:g}")

    for div in (10, 100):
        rep_low = low / div
        rep_high = high / div
        if (
            rep_low < rep_high
            and rep_low <= fallback_max
            and rep_high >= fallback_min
            and rep_high <= fallback_max * 1.5
        ):
            return (rep_low, rep_high, f"{rep_low:g} - {rep_high:g}")

    if low < high and high <= fallback_max * 2:
        return (low, high, f"{low_raw} - {high_raw}")

    if low > high and len(low_raw.replace(".", "")) <= 3:
        repaired_low = low / 10
        if repaired_low < high and high <= fallback_max * 2:
            return (repaired_low, high, f"{repaired_low:g} - {high:g}")

    return (fallback_min, fallback_max, f"{fallback_min:g} - {fallback_max:g}")


def _kft_normalize_numeric_token(raw):
    raw = raw.strip()

    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return raw

    repaired = (
        raw
        .replace("O", "0")
        .replace("o", "0")
        .replace("S", "5")
        .replace("s", "5")
    )

    if re.fullmatch(r"\d+(?:\.\d+)?", repaired):
        return repaired

    return None


def _kft_candidate_values(row, minimum, maximum, unit_pattern=None):
    range_match = re.search(r"(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)", row)

    prefix = row[:range_match.start()] if range_match else row

    if unit_pattern:
        unit_match = re.search(unit_pattern, prefix, re.IGNORECASE)
    else:
        unit_match = None

    raw_tokens = re.findall(
        r"(?<![A-Za-z])(?:\d+(?:\.\d+)?|[oOsS]\d+)(?![A-Za-z])",
        prefix
    )

    candidates = []

    for raw in raw_tokens:
        normalized = _kft_normalize_numeric_token(raw)

        if normalized is None:
            continue

        value = float(normalized)
        candidates.append((value, 0, normalized))

        digits = normalized.replace(".", "")

        if len(digits) <= 5:
            for decimals in range(1, 4):
                if len(digits) <= decimals:
                    continue

                repaired = float(digits) / (10 ** decimals)

                if minimum <= repaired <= maximum:
                    candidates.append((repaired, 1, normalized))

    if unit_match:
        number_matches = list(
            re.finditer(
                r"(?<![A-Za-z])(?:\d+(?:\.\d+)?|[oOsS]\d+)(?![A-Za-z])",
                prefix
            )
        )

        positions = []
        for match in number_matches:
            normalized = _kft_normalize_numeric_token(match.group(0))
            if normalized is None:
                continue

            positions.append((abs(match.end() - unit_match.start()), normalized))

        distance_map = {normalized: distance for distance, normalized in positions}

        candidates.sort(
            key=lambda item: (
                item[1],
                distance_map.get(item[2], 999999),
                abs(item[0] - ((minimum + maximum) / 2))
            )
        )

    unique = {}
    for value, repair_cost, raw in candidates:
        key = round(value, 8)
        old = unique.get(key)

        if old is None or repair_cost < old[1]:
            unique[key] = (value, repair_cost, raw)

    return list(unique.values())


def _extract_kft_parameters(parameters, lines):
    kft_rows = [
        ("Creatinine", r"(?:SERUM\s+)?(?:Creatinine|Cresinine|Cresinie|Creatin)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 0.55, 1.02),
        ("Urea", r"(?:SERUM\s+)?(?:\bUrea\b|\bUea\b)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 12.0, 43.0),
        ("BUN", r"(?:Blood\s+Urea\s+Nitrogen|Urea\s+Nitrogen|\bBUN\b)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 9.0, 20.0),
        ("Uric Acid", r"(?:SERUM\s+)?(?:Uric\s+Acid|Urease)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 3.5, 8.5),
        ("Calcium", r"(?:SERUM\s+)?(?:\bCalcium\b|Caloom)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 8.7, 10.0),
        ("Phosphorus", r"(?:\bPhosphorus\b|Phosphons)", r"(?:mg\s*/\s*dL|mg\s*/\s*dl|mg\s*/\s*di)", 2.0, 5.1),
        ("Sodium", r"(?:SERUM\s+)?(?:\bSodium\b|Socium)", r"(?:mEq\s*/\s*L|mmol\s*/\s*L)", 136.0, 145.0),
        ("Potassium", r"(?:SERUM\s+)?(?:\bPotassium\b|Potass)", r"(?:mEq\s*/\s*L|mmol\s*/\s*L)", 3.5, 5.1),
        ("Chloride", r"(?:SERUM\s+)?(?:\bChloride\b|Chioce)", r"(?:mEq\s*/\s*L|mmol\s*/\s*L)", 98.0, 107.0)
    ]

    for name, label_pattern, unit_pattern, fallback_min, fallback_max in kft_rows:
        if name in parameters:
            continue

        label_regex = re.compile(label_pattern, re.IGNORECASE)

        for line in lines:
            match = label_regex.search(line)

            if not match:
                continue

            row = line[match.start():].strip()

            range_match = re.search(r"(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)", row)

            minimum = fallback_min
            maximum = fallback_max
            reference_range = f"{fallback_min:g} - {fallback_max:g}"

            if range_match:
                minimum, maximum, reference_range = _kft_repair_reference_range(
                    range_match.group("low"),
                    range_match.group("high"),
                    fallback_min,
                    fallback_max
                )

            candidates = _kft_candidate_values(row, fallback_min, fallback_max, unit_pattern)

            if not candidates:
                continue

            known_candidates = [
                item for item in candidates
                if fallback_min <= item[0] <= fallback_max
            ]

            if not known_candidates:
                continue

            report_range_candidates = [
                item for item in known_candidates
                if minimum <= item[0] <= maximum
            ]

            selected_pool = report_range_candidates if report_range_candidates else known_candidates

            value, repair_cost, _ = min(
                selected_pool,
                key=lambda item: (item[1], abs(item[0] - ((minimum + maximum) / 2)))
            )

            display_value = f"{value:g}" if repair_cost > 0 else value

            add_parameter(
                parameters,
                name,
                value,
                "mEq/L" if name in {"Sodium", "Potassium", "Chloride"} else "mg/dL",
                reference_range,
                minimum,
                maximum,
                display_value=display_value
            )

            break

    # eGFR
    if "eGFR" not in parameters:
        egfr_regex = re.compile(
            r"\beGFR\b(?:\s*[HL])?\s*[:.]?\s*(?P<value>\d+(?:\.\d+)?)\s*"
            r"(?:mL|ml|mi)\s*/\s*min(?:\s*/\s*1\.73\s*(?:m2|mA2|m\^2|m²))?(?:\s*>\s*90)?",
            re.IGNORECASE
        )

        for line in lines:
            match = egfr_regex.search(line)
            if not match:
                continue

            value = float(match.group("value"))
            if 0 <= value <= 300:
                status = "Normal" if value >= 90 else "Low"
                add_parameter(
                    parameters,
                    "eGFR",
                    value,
                    "mL/min/1.73m²",
                    "> 90",
                    90,
                    None,
                    status=status
                )
            break

    # BUN / CREATININE RATIO
    if "BUN/Creatinine Ratio" not in parameters:
        ratio_regex = re.compile(
            r"BUN\s*(?:/|Crestiine|Creatinine)?\s*(?:Ratio|Rato)[\s.:]*(?P<value>\d+(?:\.\d+)?)",
            re.IGNORECASE
        )

        for line in lines:
            match = ratio_regex.search(line)
            if not match:
                continue

            try:
                value = float(match.group("value"))
            except ValueError:
                continue

            if 0 < value <= 100:
                add_parameter(
                    parameters,
                    "BUN/Creatinine Ratio",
                    value,
                    "Ratio",
                    "Not clearly recovered from OCR",
                    None,
                    None,
                    status="Not Available"
                )
            break

    # UREA / CREATININE RATIO
    if "Urea/Creatinine Ratio" not in parameters:
        ratio_regex = re.compile(
            r"UREA\s*/\s*CREATININE\s+RATIO\s*[:.]?\s*(?P<value>\d+(?:\.\d+)?)",
            re.IGNORECASE
        )

        for line in lines:
            match = ratio_regex.search(line)
            if not match:
                continue

            try:
                value = float(match.group("value"))
            except ValueError:
                continue

            if 0 < value <= 100:
                add_parameter(
                    parameters,
                    "Urea/Creatinine Ratio",
                    value,
                    "Ratio",
                    "Not clearly recovered from OCR",
                    None,
                    None,
                    status="Not Available"
                )
            break


# ============================================================
# LIPID PROFILE TABLE EXTRACTION
# ============================================================

def _repair_lipid_ratio_reference(label, low_raw, high_raw):
    low = float(low_raw)
    high = float(high_raw)
    label_lower = label.lower()

    if "ldl/hdl" in label_lower and low == 25 and high == 35:
        return 0.0, 3.5, "< 3.5"
    if "total cholesterol/hdl" in label_lower and low == 35 and high == 5:
        return 0.0, 5.0, "< 5.0"
    if low < high:
        return 0.0, high, f"{low_raw} - {high_raw}"
    return None


def _extract_lipid_profile_parameters(parameters, lines):
    row_specs = [
        ("Total Cholesterol", r"(?<![A-Za-z])Total\s+Cholesterol(?![A-Za-z])"),
        ("Triglycerides", r"(?<![A-Za-z])Triglycerides?(?:\s+level)?(?![A-Za-z])"),
        ("HDL Cholesterol", r"(?<![A-Za-z])HDL\s+Cholesterol(?![A-Za-z])"),
        ("LDL Cholesterol", r"(?<![A-Za-z])LDL\s+Cholesterol(?![A-Za-z])"),
        ("VLDL", r"(?<![A-Za-z])VLDL\s+Cholesterol(?![A-Za-z])")
    ]

    for name, label_pattern in row_specs:
        if name in parameters:
            continue
        for line in lines:
            match = re.search(
                label_pattern +
                r"\s+(?P<value>\d+(?:\.\d+)?)\s+"
                r"(?P<low>\d+(?:\.\d+)?)\s*-\s*"
                r"(?P<high>\d+(?:\.\d+)?)\s+"
                r"(?P<unit>mg\s*/\s*d[li])\b",
                line,
                re.IGNORECASE
            )
            if not match:
                continue

            value = float(match.group("value"))
            minimum = float(match.group("low"))
            maximum = float(match.group("high"))
            reference_range = f"{match.group('low')} - {match.group('high')}"

            add_parameter(
                parameters,
                name,
                value,
                "mg/dL",
                reference_range,
                minimum,
                maximum,
                status=calculate_status(value, minimum, maximum)
            )
            break

    ratio_specs = [
        ("LDL/HDL Ratio", r"(?P<label>LDL\s*/\s*HDL\s+RATIO)"),
        ("Total Cholesterol/HDL Ratio", r"(?P<label>Total\s+Cholesterol\s*/\s*HDL\s+RATIO)")
    ]

    for name, label_pattern in ratio_specs:
        if name in parameters:
            continue
        for line in lines:
            match = re.search(
                label_pattern +
                r"\s+(?P<value>\d+(?:\.\d+)?)\s+"
                r"(?P<low>\d+(?:\.\d+)?)\s*-\s*"
                r"(?P<high>\d+(?:\.\d+)?)",
                line,
                re.IGNORECASE
            )
            if not match:
                continue

            value = float(match.group("value"))
            repaired = _repair_lipid_ratio_reference(
                match.group("label"), match.group("low"), match.group("high")
            )
            if repaired:
                minimum, maximum, reference_range = repaired
            else:
                minimum = maximum = None
                reference_range = f"{match.group('low')} - {match.group('high')}"

            status = (
                calculate_status(value, minimum, maximum)
                if minimum is not None and maximum is not None
                else "Not Available"
            )

            add_parameter(
                parameters,
                name,
                value,
                "Ratio",
                reference_range,
                minimum,
                maximum,
                status=status
            )
            break


def _extract_simple_label_rows(parameters, lines):
    specs = [
        # CBC
        ("Hemoglobin", r"(?:haemoglobin|hemoglobin)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "g/dL", "13 - 17", 13, 17),
        ("RBC Count", r"(?:total\s+rbc\s+count|rbc\s+count)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "Million/cmm", "4.5 - 5.5", 4.5, 5.5),
        ("WBC Count", r"(?:total\s+wbc\s+count|total\s+leu[ck]ocyte\s+count|tlc)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "/cumm", "4000 - 10000", 4000, 10000),
        ("Platelet Count", r"platelet\s+count(?:\s*\([^)]*\))?\s*[:.-]?\s*", "/cumm", "150000 - 450000", 150000, 450000),
        ("Hematocrit", r"(?:packed\s+cell\s+volume|p\.?c\.?v|hematocrit|hct)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "40 - 50", 40, 50),
        ("MCV", r"(?:mean\s+(?:corpuscular|cell)\s+volume|m\.?c\.?v\.?)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "fL", "80 - 96", 80, 96),
        ("MCH", r"(?:mean\s+corpuscular\s+hemoglobin|m\.?c\.?h\.?)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "pg", "27 - 33", 27, 33),
        ("MCHC", r"(?:mean\s+corpuscular\s+hemoglobin\s+concentration|m\.?c\.?h\.?c\.?)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "g/dL", "32 - 36", 32, 36),
        ("RDW CV", r"r\.?d\.?w\.?\s*(?:-\s*cv)?(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "11.5 - 15", 11.5, 15),
        ("Neutrophils", r"(?:polymorphs|neutrophils)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "40 - 80", 40, 80),
        ("Lymphocytes", r"lymphocytes(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "20 - 45", 20, 45),
        ("Eosinophils", r"eosinophils(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "1 - 6", 1, 6),
        ("Monocytes", r"monocytes(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "2 - 10", 2, 10),
        ("Basophils", r"basophils(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "0 - 2", 0, 2),
        # Common chemistry
        ("Creatinine", r"(?:serum\s+)?creatinine(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "0.66 - 1.25", 0.66, 1.25),
        ("Urea", r"(?:serum\s+)?urea(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "19.3 - 43", 19.3, 43),
        ("Fasting Blood Sugar", r"(?:fasting\s+blood\s+sugar|fasting\s+glucose|fbs)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "74 - 106", 74, 106),
        ("SGPT", r"(?:s\.?g\.?p\.?t\.?|alt)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "U/L", "0 - 50", 0, 50),
        ("SGOT", r"(?:s\.?g\.?o\.?t\.?|ast)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "U/L", "17 - 59", 17, 59),
        ("Total Protein", r"total\s+protein(?:\s*\([^)]*\))?\s*[:.-]?\s*", "g/dL", "6.3 - 8.2", 6.3, 8.2),
        ("Albumin", r"(?<!micro)\balbumin(?:\s*\([^)]*\))?\s*[:.-]?\s*", "g/dL", "3.5 - 5.0", 3.5, 5.0),
        ("Globulin", r"globulin(?:\s*\([^)]*\))?\s*[:.-]?\s*", "g/dL", "2.3 - 3.5", 2.3, 3.5),
        ("Total Bilirubin", r"total\s+bilirubin(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "0.2 - 1.3", 0.2, 1.3),
        ("Calcium", r"calcium(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "8.4 - 10.2", 8.4, 10.2),
        ("Iron", r"(?<!total\s)\biron(?:\s*\([^)]*\))?\s*[:.-]?\s*", "µg/dL", "49 - 181", 49, 181),
        ("Homocysteine", r"homocysteine(?:\s*\([^)]*\))?\s*[:.-]?\s*", "µmol/L", "6 - 14.8", 6, 14.8),
        ("TSH", r"(?:thyroid\s+stimulating\s+hormone|tsh)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "µIU/mL", "0.35 - 4.94", 0.35, 4.94),
        ("T3", r"(?:triiodothyronine|t3)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "ng/mL", "0.58 - 1.59", 0.58, 1.59),
        ("T4", r"(?:thyroxine|t4)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "µg/dL", "4.87 - 11.72", 4.87, 11.72),
        ("Vitamin D", r"(?:25\s*\(?oh\)?\s*vitamin\s*d|vitamin\s*d)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "ng/mL", "30 - 100", 30, 100),
        ("Vitamin B12", r"(?:vitamin\s*b12|cyanocobalamin)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "pg/mL", "211 - 911", 211, 911),
        ("HbA1c", r"(?:hba1c|haemoglobin\s+a1c|hemoglobin\s+a1c)(?:\s*\([^)]*\))?\s*[:.-]?\s*", "%", "4.0 - 5.6", 4.0, 5.6),
        ("CRP", r"(?:c\.?r\.?p\.?|c-reactive\s+protein)\s*(?:test)?(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/L", "0 - 5", 0, 5),
        # Lipid profile rows without an inline reference interval
        ("Total Cholesterol", r"total\s+cholesterol(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "0 - 200", 0, 200),
        ("Triglycerides", r"triglycerides?(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "0 - 150", 0, 150),
        ("HDL Cholesterol", r"hdl\s+cholesterol(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "40 - 60", 40, 60),
        ("LDL Cholesterol", r"ldl\s+cholesterol(?:\s*\([^)]*\))?\s*[:.-]?\s*", "mg/dL", "0 - 100", 0, 100),
    ]

    for name, label_pattern, unit, ref, low, high in specs:
        if name in parameters:
            continue
        pattern = re.compile(label_pattern + r"(?P<value><\s*\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?)", re.I)
        for line in lines:
            match = pattern.search(line)
            if not match:
                continue
            raw = match.group("value").replace(",", "").replace(" ", "")
            try:
                value = float(raw.lstrip("<"))
            except ValueError:
                continue

            tail = line[match.end():]
            if tail.lstrip().startswith("-"):
                continue

            range_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(?!\d)", tail)
            row_low, row_high, row_ref = low, high, ref
            if range_match:
                a, b = float(range_match.group(1)), float(range_match.group(2))
                if a < b:
                    row_low, row_high = a, b
                    row_ref = f"{a:g} - {b:g}"

            if name == "Platelet Count":
                if value < 1000 and (row_low or 0) >= 100000:
                    value *= 100000
                elif value >= 10000 and row_high is not None and row_high < 100:
                    row_low = 150000
                    row_high = 450000
                    row_ref = "150000 - 450000"

            flag_match = re.search(r"(?<!/)\b([HL])\b", tail, re.I)
            status = flag_match.group(1).upper() if flag_match else None
            if status == "H":
                status = "High"
            elif status == "L":
                status = "Low"

            add_parameter(parameters, name, value, unit, row_ref, row_low, row_high, status=status)
            break


def extract_parameters(text):
    parameters = {}
    lines = normalize_lines(text)

    # Dedicated parsers first
    _extract_kft_parameters(parameters, lines)
    _extract_lipid_profile_parameters(parameters, lines)
    _extract_cbc_table_parameters(parameters, lines)

    # General row-based fallback
    _extract_simple_label_rows(parameters, lines)

    # Additional common line-based markers
    extra_specs = [
        ("Microalbumin", r"\bmicroalbumin\b", "mg/L", "0 - 16.7", 0, 16.7),
        ("Uric Acid", r"\buric\s+acid\b", "mg/dL", "3.5 - 8.5", 3.5, 8.5),
        ("Sodium", r"\bsodium\b", "mEq/L", "136 - 145", 136, 145),
        ("Potassium", r"\bpotassium\b", "mEq/L", "3.5 - 5.1", 3.5, 5.1),
        ("Chloride", r"\bchloride\b", "mEq/L", "98 - 107", 98, 107),
        ("VLDL", r"\bVLDL\b", "mg/dL", "15 - 35", 15, 35),
        ("PSA Total", r"\bPSA\s+Total\b", "ng/mL", "0 - 4", 0, 4),
    ]
    for name, label, unit, ref, low, high in extra_specs:
        if name in parameters:
            continue
        _add_line_parameter(parameters, lines, name, label, unit, ref, low, high)

    return parameters


# ============================================================
# QUALITATIVE RESULTS
# ============================================================

def _qualitative_result(results, name, result, interpretation):
    if any(item["name"] == name for item in results):
        return

    results.append({
        "name": name,
        "result": result,
        "interpretation": interpretation
    })


def extract_qualitative_results(text):
    results = []
    normalized = " ".join(normalize_lines(text))

    # HLA-B27
    hla_match = re.search(
        r"HLA[-\s]?B27\s*PCR.*?\b(NEGATIVE|POSITIVE|INVALID)\b",
        normalized,
        re.IGNORECASE
    )
    if hla_match:
        result_value = hla_match.group(1).upper()
        _qualitative_result(
            results,
            "HLA-B27 PCR, QUALITATIVE",
            result_value,
            result_value.capitalize()
        )

    # HIV
    hiv_match = re.search(
        r"HIV\s*I\s*&\s*II.*?\b(Non\s*Reactive|Reactive|Negative|Positive)\b",
        normalized,
        re.IGNORECASE
    )
    if hiv_match:
        raw = re.sub(r"\s+", " ", hiv_match.group(1)).strip()
        _qualitative_result(results, "HIV I & II Ab/Ag P24 Ag", raw, raw)

    # HBSAG
    hbsag_match = re.search(
        r"HBsAg.*?\b(Non\s*Reactive|Reactive|Negative|Positive)\b",
        normalized,
        re.IGNORECASE
    )
    if hbsag_match:
        raw = re.sub(r"\s+", " ", hbsag_match.group(1)).strip()
        _qualitative_result(results, "HBsAg", raw, raw)

    # HB ELECTROPHORESIS
    electrophoresis_match = re.search(
        r"Interpretation\s+(Negative for typical beta thalassemia trait\.)",
        normalized,
        re.IGNORECASE
    )
    if electrophoresis_match:
        _qualitative_result(
            results,
            "Hb Electrophoresis",
            electrophoresis_match.group(1).strip(),
            "Negative"
        )

    # eGFR CATEGORY
    egfr_category_match = re.search(
        r"\bEGFR\s+CATEGORY\s+(G[1-5](?:A|B)?)\b",
        normalized,
        re.IGNORECASE
    )
    if egfr_category_match:
        _qualitative_result(
            results,
            "eGFR Category",
            egfr_category_match.group(1).upper(),
            "Reported category"
        )

    # URINE GLUCOSE
    urine_glucose_match = re.search(
        r"Urine Glucose\s+(Present\s*(?:\(\+\)|\+)|Absent)",
        normalized,
        re.IGNORECASE
    )
    if urine_glucose_match:
        raw = urine_glucose_match.group(1).strip()
        interpretation = "Present" if raw.lower().startswith("present") else "Absent"
        _qualitative_result(results, "Urine Glucose", raw, interpretation)

    # URINALYSIS
    urine_items = [
        ("Urine Protein", r"Urine Protein\s+(Present|Absent|Negative|Positive)"),
        ("Urine Bilirubin", r"Urine Bilirubin\s+(Present|Absent|Negative|Positive)"),
        ("Urine Urobilinogen", r"Urobilinogen\s+(Present|Absent|Normal|Negative|Positive)"),
        ("Urine Ketone", r"Ketone\s+(Present|Absent|Negative|Positive)"),
        ("Urine Nitrite", r"Nitrite\s+(Present|Absent|Negative|Positive)"),
        ("Urine Casts", r"Casts\s+(Present|Absent|Negative)"),
        ("Urine Crystals", r"Crystals\s+(Present|Absent|Negative)"),
        ("Urine Amorphous", r"Amorphous\s+(Present|Absent|Negative)")
    ]

    for name, pattern in urine_items:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
            _qualitative_result(results, name, raw, raw)

    return results


# ============================================================
# PATIENT INFORMATION
# ============================================================

def extract_patient_info(text):
    text = text.replace("\xa0", " ")
    patient_info = {
        "age": "Not Available",
        "gender": "Not Available",
        "report_status": "Not Available",
        "report_date": "Not Available"
    }

    age_match = re.search(
        r"\bAge\s*/\s*(?:Sex|Gender)\s*[:.]?\s*(\d{1,3})\s*(?:Years?|YRS?|Y)\b",
        text,
        re.IGNORECASE
    )

    if not age_match:
        age_match = re.search(
            r"\bAge\s*(?:/|:)?\s*(\d{1,3})\s*(?:Years?|YRS?|Y)\b",
            text,
            re.IGNORECASE
        )

    if not age_match:
        age_match = re.search(
            r"\bAge\s*/\s*(?:Sex|Gender)\s*[:.]?\s*(\d{1,3})\s*/",
            text,
            re.IGNORECASE
        )

    if age_match:
        age_num = int(age_match.group(1))
        if 0 < age_num <= 120:
            patient_info["age"] = f"{age_num} Years"

    gender_match = re.search(r"\b(?:Male|Female)\b", text, re.IGNORECASE)
    if gender_match:
        patient_info["gender"] = gender_match.group(0).capitalize()

    if patient_info["gender"] == "Not Available":
        sex_match = re.search(
            r"\bAge\s*/\s*(?:Sex|Gender)\s*[:.]?\s*\d{1,3}\s*(?:Years?|YRS?|Y)\s*/\s*([MF])\b",
            text,
            re.IGNORECASE
        )
        if sex_match:
            patient_info["gender"] = "Male" if sex_match.group(1).upper() == "M" else "Female"

    date_token = (
        r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
        r"(?:\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?"
    )

    report_date_patterns = [
        rf"\b(?:Report\s*Date|Reported\s*on|Reportedon|Collected\s*on|Sample\s*Date)\s*:?\s*({date_token})",
        rf"\bDate\s*:?\s*({date_token})"
    ]

    for pattern in report_date_patterns:
        report_date_match = re.search(pattern, text, re.IGNORECASE)
        if report_date_match:
            patient_info["report_date"] = report_date_match.group(1).strip()
            break

    status_match = re.search(
        r"Status\s*:?\s*(Final|Preliminary|Draft)",
        text,
        re.IGNORECASE
    )

    if not status_match:
        status_match = re.search(
            r"\b(Final|Preliminary|Draft)\b",
            text,
            re.IGNORECASE
        )

    if status_match:
        patient_info["report_status"] = status_match.group(1).capitalize()
    elif patient_info["report_date"] != "Not Available":
        patient_info["report_status"] = "Reported"

    return patient_info


# ============================================================
# REPORT TYPE
# ============================================================

def detect_report_type(text):
    text_lower = text.lower()

    if re.search(
        r"kidney\s+function\s+test|kidney\s+panel|kft\s*[-.]?\s*serum|renal\s+function\s+test",
        text_lower
    ):
        return "Kidney / Renal Function Report"

    if re.search(r"hla[-\s]?b27\s*pcr", text_lower):
        return "HLA-B27 PCR Report"

    if "hb electrophoresis" in text_lower or "hemoglobin electrophoresis" in text_lower:
        if not any(key in text_lower for key in ["complete blood count", "lipid profile", "thyroid"]):
            return "Hb Electrophoresis Report"

    families = {
        "CBC / Hematology": ["complete blood count", "cbc", "haemogram", "hemogram", "hemoglobin", "platelet count"],
        "Lipid Profile": ["lipid profile", "triglyceride", "hdl cholesterol", "direct ldl"],
        "Blood Glucose": ["fasting blood sugar", "blood glucose", "fasting glucose"],
        "HbA1c": ["hba1c", "glycated hemoglobin"],
        "Thyroid": ["thyroid function", "triiodothyronine", "thyroxine", "thyroid stimulating hormone"],
        "Vitamin D": ["25(oh) vitamin d", "vitamin d"],
        "Vitamin B12": ["vitamin b12"],
        "Iron Studies": ["total iron binding capacity", "tibc", "transferrin saturation"],
        "Kidney / Renal": ["creatinine", "blood urea nitrogen", "urea", "uric acid"],
        "Liver": ["sgpt", "sgot", "bilirubin", "liver function"],
        "Electrolytes": ["sodium", "potassium", "chloride"],
        "Homocysteine": ["homocysteine"],
        "CRP / Inflammation": ["c-reactive protein", "crp"],
        "PSA": ["prostate specific antigen", "psa"],
        "Urinalysis": ["urinalysis", "urine examination", "urine glucose", "pus cells", "specific gravity"],
        "Infectious Screening": ["hiv i & ii", "hbsag", "hepatitis b surface antigen"]
    }

    matched_families = [
        family
        for family, keywords in families.items()
        if any(keyword in text_lower for keyword in keywords)
    ]

    if len(matched_families) >= 2:
        return "Comprehensive Laboratory Test Report"

    if matched_families:
        family = matched_families[0]

        mapping = {
            "CBC / Hematology": "Blood Test Report",
            "Lipid Profile": "Lipid Profile Report",
            "Blood Glucose": "Blood Glucose Report",
            "HbA1c": "HbA1c Report",
            "Thyroid": "Thyroid Function Test Report",
            "Vitamin D": "Vitamin D Report",
            "Vitamin B12": "Vitamin B12 Report",
            "Iron Studies": "Iron Studies Report",
            "Kidney / Renal": "Kidney / Renal Function Report",
            "Liver": "Liver Function Report",
            "Electrolytes": "Electrolyte Report",
            "Homocysteine": "Homocysteine Report",
            "CRP / Inflammation": "Inflammatory Marker Report",
            "PSA": "PSA Report",
            "Urinalysis": "Urinalysis Report",
            "Infectious Screening": "Infectious Screening Report"
        }

        return mapping.get(family, "Medical Laboratory Report")

    return "Medical Laboratory Report"


# ============================================================
# TEST NAME
# ============================================================

def extract_test_name(text, report_type=""):
    if report_type == "Comprehensive Laboratory Test Report":
        return "Multiple Laboratory Panels"

    test_patterns = [
        (r"HLA[-\s]?B27\s*PCR", "HLA-B27 PCR"),
        (r"\b(?:Complete Blood Count|CBC|Haemogram|Hemogram)\b", "Complete Blood Count"),
        (r"Lipid Profile", "Lipid Profile"),
        (r"HbA1c|Glycated Hemoglobin", "HbA1c"),
        (r"Thyroid Function Test", "Thyroid Function Test"),
        (r"Vitamin D", "Vitamin D"),
        (r"Vitamin B12", "Vitamin B12"),
        (r"Urinalysis|Urine Examination", "Urinalysis"),
        (r"HB Electrophoresis|Hemoglobin Electrophoresis", "Hb Electrophoresis"),
        (r"Homocysteine", "Homocysteine"),
        (r"PSA[-\s]*Prostate Specific Antigen", "PSA"),
        (r"Kidney\s+Function\s+Test|Kidney\s+Panel|KFT\s*[-.]?\s*Serum|Renal\s+Function\s+Test", "Kidney / Renal Function"),
        (r"Creatinine|Cresinine|Cresinie|Kidney|Renal Function", "Kidney / Renal Function"),
        (r"SGPT|SGOT|Liver Function", "Liver Function"),
        (r"HIV\s*I\s*&\s*II", "HIV Screening"),
        (r"HBsAg", "HBsAg")
    ]

    for pattern, name in test_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return name

    return "Not Available"


# ============================================================
# TEST RESULT
# ============================================================

def extract_test_result(text, report_type, parameter_analysis=None, qualitative_results=None):
    if report_type == "HLA-B27 PCR Report":
        text_upper = text.upper()
        if re.search(r"\bNEGATIVE\b", text_upper):
            return "NEGATIVE"
        if re.search(r"\bPOSITIVE\b", text_upper):
            return "POSITIVE"
        if re.search(r"\bINVALID\b", text_upper):
            return "INVALID"

    if parameter_analysis:
        total = len(parameter_analysis)
        attention = sum(
            1 for item in parameter_analysis.values()
            if item.get("status") not in ["Normal", "Optimal", "Not Available"]
        )
        if attention == 0:
            return f"All {total} Parameters Normal"
        label = "Parameter" if attention == 1 else "Parameters"
        return f"{attention} of {total} {label} Out of Range"

    if qualitative_results:
        return f"{len(qualitative_results)} Qualitative Finding(s)"

    return "Detailed Below"


# ============================================================
# RESULT SUMMARY
# ============================================================

def create_result_summary(
    report_type,
    test_name,
    test_result,
    parameter_analysis,
    qualitative_results
):
    if test_result in ["NEGATIVE", "POSITIVE", "INVALID"]:
        if test_result == "NEGATIVE":
            return (
                f"The uploaded {report_type} reports a "
                f"negative result for {test_name}. "
                "The result shown here reflects the uploaded "
                "laboratory document and is presented for "
                "general informational purposes."
            )

        if test_result == "POSITIVE":
            return (
                f"The uploaded {report_type} reports a "
                f"positive result for {test_name}. "
                "The reported result should be reviewed with "
                "a qualified healthcare professional in the "
                "appropriate clinical context."
            )

        return (
            f"The uploaded {report_type} reports an "
            f"invalid result for {test_name}."
        )

    total = len(parameter_analysis)

    normal = sum(
        1
        for item in parameter_analysis.values()
        if item["status"] in ["Normal", "Optimal"]
    )

    not_available = sum(
        1
        for item in parameter_analysis.values()
        if item["status"] == "Not Available"
    )

    attention = total - normal - not_available
    qualitative_count = len(qualitative_results)

    if total == 0:
        if qualitative_count > 0:
            return (
                f"The report contains {qualitative_count} "
                "qualitative laboratory result(s). "
                "These results are displayed as reported in "
                "the uploaded document. Clinical interpretation "
                "should consider the patient's history and "
                "other relevant findings."
            )

        return (
            "No structured laboratory parameters were "
            "successfully identified from the uploaded report."
        )

    return (
        f"This report contains {total} extracted numeric "
        f"health parameter(s). {normal} parameter(s) are "
        "within the extracted reference range, while "
        f"{attention} parameter(s) are outside the extracted "
        "reference range or require attention. "
        f"{qualitative_count} qualitative result(s) were also "
        "identified. "
        "These classifications are intended for general "
        "informational purposes and should not be considered "
        "a medical diagnosis."
    )


# ============================================================
# FINDINGS
# ============================================================

def create_findings(parameter_analysis):
    findings = []

    attention_statuses = [
        "High",
        "Very High",
        "Low",
        "Deficient",
        "Insufficient",
        "Borderline High",
        "Prediabetes Range",
        "Above Optimal"
    ]

    for name, data in parameter_analysis.items():
        status = data["status"]

        if status in attention_statuses:
            findings.append({
                "name": name,
                "value": data["value"],
                "unit": data["unit"],
                "status": status,
                "message": (
                    f"{name} is classified as "
                    f"{status} based on the extracted "
                    "reference information."
                )
            })

    return findings


# ============================================================
# HOME & UPLOAD ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/upload")
def upload():
    return render_template("upload.html")


# ============================================================
# SMART TEXT & SCANNED PDF EXTRACTION
# ============================================================

def preprocess_image_for_ocr(pil_image):
    """Fixes mobile rotation, upscales low-res images, and enhances contrast for OCR."""
    img = ImageOps.exif_transpose(pil_image)

    min_width = 1600
    if img.width < min_width:
        scale = min_width / img.width
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(img)
    enhanced = ImageOps.autocontrast(gray)
    return enhanced


def _run_tesseract_with_fallback(pil_image):
    """Runs Tesseract with PSM 6 first, falling back to PSM 3 for multi-column layouts."""
    processed_img = preprocess_image_for_ocr(pil_image)
    text_psm6 = pytesseract.image_to_string(processed_img, config="--psm 6")

    if extract_parameters(text_psm6) or extract_qualitative_results(text_psm6):
        return text_psm6

    text_psm3 = pytesseract.image_to_string(processed_img, config="--psm 3")
    return text_psm3 if len(text_psm3.strip()) > len(text_psm6.strip()) else text_psm6


def extract_text_from_file(file_path):
    extracted_text = ""

    if file_path.lower().endswith(".pdf"):
        # 1. Try normal digital text extraction first
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"
        except Exception as error:
            print("PyPDF Read Error:", error)

        # 2. Run OCR if text is too short OR if digital text yielded zero lab parameters
        has_lab_data = bool(
            extract_parameters(extracted_text)
            or extract_qualitative_results(extracted_text)
        )

        if len(extracted_text.strip()) < 50 or not has_lab_data:
            print("Scanned or image-based PDF detected! Running high-DPI OCR...")
            ocr_text = ""
            try:
                pdf_doc = fitz.open(file_path)
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc.load_page(page_num)
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_text += _run_tesseract_with_fallback(img) + "\n"
                pdf_doc.close()

                if ocr_text.strip():
                    extracted_text = (
                        ocr_text
                        if not has_lab_data
                        else extracted_text + "\n" + ocr_text
                    )
            except Exception as error:
                print("Scanned PDF OCR Error:", error)
    else:
        # Image upload (.jpg, .png, .jpeg, .webp, etc.)
        try:
            with Image.open(file_path) as image:
                extracted_text = _run_tesseract_with_fallback(image)
        except Exception as error:
            print("Image OCR Error:", error)

    return extracted_text


# ============================================================
# PROCESSING
# ============================================================

@app.route("/processing", methods=["GET", "POST"])
def processing():
    if request.method == "POST":
        report_file = request.files.get("report_file")

        if not report_file:
            return redirect(url_for("upload"))

        filename = secure_filename(report_file.filename)

        if not filename:
            return redirect(url_for("upload"))

        unique_filename = uuid.uuid4().hex[:8] + "_" + filename
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
        report_file.save(file_path)

        # File content hash for duplicate upload detection
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        # TEXT EXTRACTION (Supports Digital PDF, Scanned PDF & Images)
        extracted_text = extract_text_from_file(file_path)

        # Privacy & Storage Cleanup: delete uploaded file after text extraction
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass

        # ANALYSIS
        parameter_analysis = extract_parameters(extracted_text)
        qualitative_results = extract_qualitative_results(extracted_text)

        if not parameter_analysis and not qualitative_results:
            print("--- RAW OCR TEXT DEBUG ---\n", extracted_text[:1000])

        report_type = detect_report_type(extracted_text)
        test_name = extract_test_name(extracted_text, report_type)
        test_result = extract_test_result(
        extracted_text,
        report_type,
        parameter_analysis,
        qualitative_results
        )
        patient_info = extract_patient_info(extracted_text)
        if patient_info["report_date"] == "Not Available":
            patient_info["report_date"] = datetime.now().strftime("%d/%m/%Y")
        if patient_info["report_status"] == "Not Available":
            patient_info["report_status"] = "Final"
        findings = create_findings(parameter_analysis)

        result_summary = create_result_summary(
            report_type,
            test_name,
            test_result,
            parameter_analysis,
            qualitative_results
        )

        # ANALYSIS ID
        analysis_id = uuid.uuid4().hex

        analysis_store[analysis_id] = {
            "report_name": filename,
            "analysis_date": datetime.now().strftime("%d %B %Y, %I:%M %p"),
            "report_type": report_type,
            "test_name": test_name,
            "test_result": test_result,
            "patient_info": patient_info,
            "report_date": patient_info.get("report_date", "Not Available"),
            "parameters": parameter_analysis,
            "parameter_analysis": parameter_analysis,
            "qualitative_results": qualitative_results,
            "findings": findings,
            "result_summary": result_summary
        }

        session["analysis_id"] = analysis_id

        # REPORT HISTORY (WITH DUPLICATE PREVENTION)
        is_duplicate = any(
            entry.get("file_hash") == file_hash
            for entry in report_history
        )

        if not is_duplicate:
            extracted_date = patient_info.get("report_date", "Not Available")
            if extracted_date == "Not Available":
                extracted_date = datetime.now().strftime("%d/%m/%Y")

            history_entry = {
                "report_id": analysis_id,
                "file_hash": file_hash,
                "report_name": filename,
                "report_type": report_type,
                "test_name": test_name,
                "test_result": test_result,
                "patient_info": patient_info,
                "report_date": extracted_date,
                "report_date_display": format_report_date(extracted_date),
                "analysis_date": analysis_store[analysis_id]["analysis_date"],
                "parameters": parameter_analysis,
                "qualitative_results": qualitative_results
            }

            report_history.append(history_entry)
            save_report_history(report_history)

            

    return redirect(url_for("processing_page"))


@app.route("/processing-page")
def processing_page():
    return render_template("processing.html")


# ============================================================
# ANALYSIS
# ============================================================

@app.route("/analysis")
def analysis():
    analysis_id = session.get("analysis_id")
    data = get_analysis_data(analysis_id)

    if not data:
        return render_template(
            "analysis.html",
            report_name="Not Available",
            analysis_date="Not Available",
            report_type="Not Available",
            test_name="Not Available",
            test_result="Not Available",
            patient_info={
                "age": "Not Available",
                "gender": "Not Available",
                "report_status": "Not Available",
                "report_date": "Not Available"
            },
            result_summary="No summary available.",
            parameters={},
            parameter_analysis={},
            qualitative_results=[],
            findings=[]
        )

    return render_template(
        "analysis.html",
        report_name=data["report_name"],
        analysis_date=data["analysis_date"],
        report_type=data["report_type"],
        test_name=data["test_name"],
        test_result=data["test_result"],
        patient_info=data["patient_info"],
        report_date=data.get(
            "report_date",
            data["patient_info"].get("report_date", "Not Available")
        ),
        result_summary=data["result_summary"],
        parameters=data["parameters"],
        parameter_analysis=data["parameter_analysis"],
        qualitative_results=data["qualitative_results"],
        findings=data["findings"]
    )


# ============================================================
# PERSONALIZED DIET ENGINE
# ============================================================

def _unique(items):
    return list(dict.fromkeys(items))


def _diet_rule(
    focus,
    include=None,
    limit=None,
    habits=None,
    priority="General"
):
    return {
        "focus": focus,
        "include": include or [],
        "limit": limit or [],
        "habits": habits or [],
        "priority": priority
    }


def build_personalized_diet(parameter_analysis):
    base_include = [
        "Include a variety of vegetables and seasonal fruits",
        "Prefer whole grains and minimally processed cereals",
        "Include appropriate protein-rich foods such as dal, beans, legumes, curd or other suitable sources",
        "Include nuts and seeds in appropriate portions",
        "Maintain adequate water intake unless a healthcare professional has advised a fluid restriction"
    ]

    base_habits = [
        "Maintain regular meal timing",
        "Choose mostly minimally processed foods",
        "Stay physically active as appropriate",
        "Monitor future reports when advised",
        "Discuss persistent or significant abnormalities with a qualified healthcare professional"
    ]

    rules = [
        # 0: Blood sugar / HbA1c
        _diet_rule(
            "Blood sugar / HbA1c requires dietary attention",
            include=[
                "Prefer high-fiber carbohydrate sources such as whole grains, vegetables and legumes",
                "Pair carbohydrate-containing foods with protein or fiber-rich foods where appropriate",
                "Choose whole or minimally processed foods more often"
            ],
            limit=[
                "Limit frequent intake of sugary drinks and sweetened beverages",
                "Limit foods with large amounts of added sugar",
                "Avoid making refined and highly processed carbohydrate foods a frequent choice"
            ],
            habits=[
                "Prefer consistent meal patterns",
                "Monitor glucose-related reports as advised"
            ],
            priority="High"
        ),
        # 1: Triglycerides
        _diet_rule(
            "Triglycerides require dietary attention",
            include=[
                "Emphasize vegetables, legumes and other fiber-rich foods",
                "Prefer minimally processed carbohydrate sources",
                "Use unsaturated-fat food sources in appropriate portions"
            ],
            limit=[
                "Limit frequent intake of sugary foods and sweetened beverages",
                "Limit heavily processed foods",
                "Avoid making deep-fried foods a frequent choice"
            ],
            habits=[
                "Keep portions of refined carbohydrates moderate",
                "Maintain regular physical activity as appropriate"
            ],
            priority="High"
        ),
        # 2: LDL / Cholesterol
        _diet_rule(
            "LDL / cholesterol requires dietary attention",
            include=[
                "Include vegetables, fruits, whole grains and legumes regularly",
                "Prefer sources of unsaturated fats such as nuts and seeds in appropriate portions",
                "Choose minimally processed foods more often"
            ],
            limit=[
                "Limit frequent consumption of heavily fried foods",
                "Limit foods high in saturated fat",
                "Avoid making highly processed foods a frequent choice"
            ],
            habits=[],
            priority="High"
        ),
        # 3: Low Hemoglobin
        _diet_rule(
            "Hemoglobin is low",
            include=[
                "Include iron-containing foods such as legumes, beans, leafy vegetables and other suitable sources",
                "Combine plant-based iron sources with vitamin-C-rich foods such as citrus fruits, guava or tomatoes",
                "Include a varied protein-rich diet"
            ],
            limit=[
                "Avoid taking tea or coffee immediately with iron-focused meals when possible"
            ],
            habits=[
                "Discuss persistent low hemoglobin with a healthcare professional"
            ],
            priority="High"
        ),
        # 4: Low Vitamin B12
        _diet_rule(
            "Vitamin B12 is low",
            include=[
                "Include suitable vitamin-B12-containing or fortified foods according to individual dietary preferences",
                "Use fortified foods where appropriate"
            ],
            limit=[],
            habits=[
                "Discuss the result with a healthcare professional because food alone may not always address low B12"
            ],
            priority="High"
        ),
        # 5: Low Vitamin D
        _diet_rule(
            "Vitamin D is low",
            include=[
                "Include appropriate vitamin-D-fortified foods where suitable",
                "Include foods containing vitamin D that fit the person's dietary pattern"
            ],
            limit=[],
            habits=[
                "Discuss vitamin-D management and appropriate sunlight exposure with a healthcare professional"
            ],
            priority="High"
        ),
        # 6: High Uric Acid
        _diet_rule(
            "Uric acid requires dietary attention",
            include=[
                "Maintain adequate hydration unless fluid restriction has been advised",
                "Prefer a balanced eating pattern with plenty of vegetables and minimally processed foods"
            ],
            limit=[
                "Discuss the appropriate intake of purine-rich foods with a healthcare professional rather than using a blanket elimination list"
            ],
            habits=[
                "Maintain hydration according to professional advice"
            ],
            priority="High"
        ),
        # 7: High Homocysteine
        _diet_rule(
            "Homocysteine is high",
            include=[
                "Include a varied diet containing folate- and B-vitamin-rich foods such as leafy vegetables and legumes",
                "Include a variety of nutrient-dense foods"
            ],
            limit=[],
            habits=[
                "Discuss the elevated result and possible nutritional factors with a healthcare professional"
            ],
            priority="Monitor"
        ),
        # 8: Kidney parameters
        _diet_rule(
            "Kidney-related parameters require caution",
            include=[
                "Keep meals balanced and avoid making large dietary changes based on a single laboratory result",
                "Follow any fluid or nutrient restrictions only when specifically advised by a healthcare professional"
            ],
            limit=[
                "Do not start a high-protein, low-sodium or fluid-restricted diet solely from this report"
            ],
            habits=[
                "Discuss abnormal kidney-related results with a qualified healthcare professional before making major dietary changes"
            ],
            priority="High"
        ),
        # 9: Elevated IgE
        _diet_rule(
            "IgE is elevated",
            include=[],
            limit=[
                "Do not eliminate foods solely because total IgE is elevated"
            ],
            habits=[
                "Discuss allergy symptoms and food triggers with a qualified healthcare professional if relevant"
            ],
            priority="Monitor"
        ),
        # 10: Liver enzymes (SGOT / SGPT / Bilirubin)
        _diet_rule(
            "Liver-related parameters require dietary attention",
            include=[
                "Favor home-cooked, lightly spiced meals with plenty of seasonal vegetables and fruits",
                "Include adequate fiber from whole grains, oats and legumes",
                "Stay well hydrated with plain water or light homemade fluids"
            ],
            limit=[
                "Strictly avoid alcohol and unprescribed herbal or protein supplements",
                "Limit deep-fried, oily, fast food and high-sugar items"
            ],
            habits=[
                "Discuss abnormal liver enzyme levels with a healthcare professional"
            ],
            priority="High"
        ),
        # 11: Elevated CRP (Inflammation)
        _diet_rule(
            "Inflammatory marker (CRP) is elevated",
            include=[
                "Include antioxidant-rich colorful vegetables, berries, citrus fruits and turmeric/ginger in regular cooking",
                "Prefer healthy unsaturated fats from walnuts, flaxseeds or almonds in moderate portions"
            ],
            limit=[
                "Limit ultra-processed packaged snacks, refined sugar and deep-fried foods"
            ],
            habits=[
                "Prioritize adequate rest and follow up with a doctor to identify the underlying cause of elevated CRP"
            ],
            priority="High"
        ),
        # 12: Low Platelet Count
        _diet_rule(
            "Platelet count is low",
            include=[
                "Maintain steady hydration with water, coconut water or clear soups",
                "Include nutrient-dense foods rich in folate, vitamin B12, iron and vitamin C (leafy greens, citrus fruits, dal)"
            ],
            limit=[
                "Avoid alcohol and self-medicating with over-the-counter painkillers without medical advice"
            ],
            habits=[
                "Consult a qualified doctor promptly for evaluation and repeat platelet monitoring"
            ],
            priority="High"
        ),
        # 13: Low HDL Cholesterol
        _diet_rule(
            "HDL (protective) cholesterol is low",
            include=[
                "Include sources of healthy unsaturated fats such as almonds, walnuts, chia/flax seeds and olive/mustard oil in moderation",
                "Include soluble-fiber foods like oats, barley, beans and whole fruits"
            ],
            limit=[
                "Avoid trans fats, vanaspati and repeated-use frying oils"
            ],
            habits=[
                "Incorporate regular aerobic physical activity (such as brisk walking) as appropriate"
            ],
            priority="Monitor"
        ),
        # 14: Thyroid (TSH)
        _diet_rule(
            "Thyroid marker (TSH) is outside reference range",
            include=[
                "Eat balanced, regular meals with adequate protein, selenium- and zinc-rich foods (whole grains, legumes, nuts, seeds)",
                "Use iodized salt in normal household amounts"
            ],
            limit=[
                "Avoid starting high-dose iodine or kelp supplements without medical supervision"
            ],
            habits=[
                "Review thyroid results with a doctor; if prescribed thyroid medication, maintain consistent timing away from calcium/iron supplements"
            ],
            priority="High"
        )
    ]

    focus_areas = []
    foods_to_include = []
    foods_to_limit = []
    personalized_habits = []
    triggered_rules = []
    normal_parameters = []
    caution_flags = []

    for name, parameter in (parameter_analysis or {}).items():
        status = str(parameter.get("status", "")).strip()
        name_lower = name.lower()

        if status == "Normal":
            normal_parameters.append(name)

        matched_rules = []

        if (
            "fasting blood sugar" in name_lower
            or "blood sugar" in name_lower
            or "glucose" in name_lower
            or "hba1c" in name_lower
        ) and status in ["High", "Prediabetes Range"]:
            matched_rules.append(rules[0])

        if "triglyceride" in name_lower and status in ["Borderline High", "High", "Very High"]:
            matched_rules.append(rules[1])

        if (
            "ldl cholesterol" in name_lower
            or name_lower == "total cholesterol"
            or name_lower == "cholesterol"
            or "non-hdl" in name_lower
        ) and status in ["Above Optimal", "Borderline High", "High", "Very High"]:
            matched_rules.append(rules[2])

        if "hemoglobin" in name_lower and status == "Low":
            matched_rules.append(rules[3])

        if "vitamin b12" in name_lower and status == "Low":
            matched_rules.append(rules[4])

        if "vitamin d" in name_lower and status in ["Low", "Deficient", "Insufficient"]:
            matched_rules.append(rules[5])

        if "uric acid" in name_lower and status in ["High", "Very High"]:
            matched_rules.append(rules[6])

        if "homocysteine" in name_lower and status in ["High", "Very High"]:
            matched_rules.append(rules[7])

        if (
            any(term in name_lower for term in [
                "creatinine", "urea", "bun", "egfr", "kidney"
            ])
            and status not in ["Normal", "Not Available", ""]
        ):
            matched_rules.append(rules[8])

        if name_lower == "ige" and status in ["High", "Very High"]:
            matched_rules.append(rules[9])

        if any(term in name_lower for term in ["sgot", "sgpt", "ast", "alt", "bilirubin"]) and status in ["High", "Low"]:
            matched_rules.append(rules[10])

        if name_lower == "crp" and status in ["High", "Very High"]:
            matched_rules.append(rules[11])

        if "platelet" in name_lower and status == "Low":
            matched_rules.append(rules[12])

        if "hdl cholesterol" in name_lower and status == "Low":
            matched_rules.append(rules[13])

        if name_lower in ["tsh", "t3", "t4"] and status in ["High", "Low"]:
            matched_rules.append(rules[14])

        for rule in matched_rules:
            if rule not in triggered_rules:
                triggered_rules.append(rule)

            focus_areas.append(f"{name}: {status} – {rule['focus']}")
            foods_to_include.extend(rule["include"])
            foods_to_limit.extend(rule["limit"])
            personalized_habits.extend(rule["habits"])

        if status in ["High", "Very High", "Low", "Deficient", "Insufficient", "Borderline High", "Prediabetes Range"] and not matched_rules:
            caution_flags.append(
                f"{name}: {status} – report-specific dietary guidance was not generated for this parameter."
            )

    foods_to_include = _unique(base_include + foods_to_include)
    foods_to_limit = _unique(foods_to_limit)
    personalized_habits = _unique(base_habits + personalized_habits)
    normal_parameters = _unique(normal_parameters)
    caution_flags = _unique(caution_flags)

    if triggered_rules:
        priority_order = {"High": 0, "Monitor": 1, "General": 2}
        triggered_rules.sort(key=lambda item: priority_order.get(item["priority"], 3))

        personalization_summary = (
            "Guidance was generated from the report parameters that were "
            "classified outside their displayed reference information. "
            "Normal parameters were not used to create restrictive food rules."
        )
    else:
        personalization_summary = (
            "No report-specific dietary rule was triggered. The page therefore "
            "shows balanced general guidance rather than applying unnecessary restrictions."
        )

    meal_plan = {
        "Breakfast": "Vegetable poha/upma or oats with a suitable protein-rich side",
        "Lunch": "Whole-grain roti or brown rice with dal/beans, vegetables and curd where suitable",
        "Snack": "A fruit or a small portion of nuts/seeds",
        "Dinner": "Vegetable-based meal with dal/beans and a suitable whole-grain option"
    }

    rule_focus = " ".join(rule["focus"].lower() for rule in triggered_rules)

    if "blood sugar" in rule_focus or "hba1c" in rule_focus:
        meal_plan.update({
            "Breakfast": "Vegetable oats/poha with a protein-rich side; avoid making sweetened breakfast foods routine",
            "Lunch": "2 small whole-grain rotis with dal, vegetables and salad",
            "Snack": "Whole fruit with a small portion of nuts/seeds",
            "Dinner": "Vegetable dal or bean-based meal with a moderate whole-grain portion"
        })

    if "triglycerides" in rule_focus:
        meal_plan.update({
            "Breakfast": "Vegetable oats/poha or another minimally processed breakfast",
            "Lunch": "Dal/beans, plenty of vegetables and a moderate whole-grain portion",
            "Snack": "Whole fruit or a small portion of nuts/seeds instead of sugary snacks",
            "Dinner": "Vegetable-rich dal/bean meal with a moderate carbohydrate portion"
        })

    if "ldl / cholesterol" in rule_focus or "hdl" in rule_focus:
        meal_plan.update({
            "Breakfast": "Oats/vegetable poha with walnuts, almonds or flaxseeds in an appropriate portion",
            "Lunch": "Dal/beans, vegetables and whole grains; prefer less-fried preparation",
            "Snack": "Fruit or a small portion of unsalted nuts",
            "Dinner": "Vegetable and legume-based meal with a suitable whole-grain option"
        })

    if "hemoglobin is low" in rule_focus:
        meal_plan.update({
            "Breakfast": "Iron-containing breakfast option such as legumes/beans or fortified foods, with a vitamin-C-rich fruit",
            "Lunch": "Dal/beans with leafy vegetables and a vitamin-C-rich salad or fruit",
            "Snack": "Vitamin-C-rich fruit with a suitable snack",
            "Dinner": "Legume-based meal with vegetables and a suitable whole-grain option"
        })

    if "liver-related" in rule_focus or "crp" in rule_focus:
        meal_plan.update({
            "Breakfast": "Light, home-cooked oats/dalia or vegetable poha with seasonal fruit",
            "Lunch": "Simple dal, lightly cooked seasonal vegetables, whole-grain roti and fresh salad",
            "Snack": "Fresh fruit, coconut water or a small handful of soaked nuts",
            "Dinner": "Light khichdi or vegetable dal with whole-grain roti; avoid heavy fried meals at night"
        })

    if "platelet count is low" in rule_focus:
        meal_plan.update({
            "Breakfast": "Nutritious home-cooked breakfast with a vitamin-C-rich fruit (such as papaya, orange or kiwi)",
            "Lunch": "Dal/legumes, leafy greens, whole-grain roti and curd",
            "Snack": "Fresh fruit with coconut water or homemade clear soup for steady hydration",
            "Dinner": "Soft, easily digestible dal-vegetable meal with whole grains"
        })

    if "kidney-related parameters" in rule_focus:
        meal_plan = {
            "Breakfast": "Simple balanced breakfast using familiar foods; avoid adding supplements or extreme diet changes",
            "Lunch": "Balanced meal with vegetables, grains and a suitable protein source according to professional advice",
            "Snack": "Simple fruit or other suitable snack according to the individual's dietary advice",
            "Dinner": "Balanced, moderate meal following any clinician-provided kidney dietary restrictions"
        }

    if normal_parameters and not triggered_rules:
        guidance_message = (
            "All extracted numeric parameters used by the diet engine are currently "
            "within their displayed reference ranges, so no restrictive dietary rule "
            "has been added."
        )
    elif triggered_rules:
        guidance_message = (
            "This guidance is generated from the uploaded report using predefined "
            "rules. It is educational report-based guidance, not a medical diet prescription."
        )
    else:
        guidance_message = (
            "The uploaded report did not provide enough applicable numeric information "
            "for a report-specific dietary rule."
        )

    return {
        "dietary_guidance": foods_to_include,
        "limiting_guidance": foods_to_limit,
        "health_habits": personalized_habits,
        "focus_areas": focus_areas,
        "normal_parameters": normal_parameters,
        "caution_flags": caution_flags,
        "triggered_rules": triggered_rules,
        "meal_plan": meal_plan,
        "personalization_summary": personalization_summary,
        "guidance_message": guidance_message
    }


@app.route("/diet")
def diet():
    analysis_id = session.get("analysis_id")
    data = get_analysis_data(analysis_id)

    if not data:
        engine = build_personalized_diet({})

        return render_template(
            "diet.html",
            report_type="No Report Available",
            patient_info={},
            report_name="No Report Available",
            analysis_date="Not Available",
            parameter_analysis={},
            dietary_guidance=engine.get("dietary_guidance", []),
            limiting_guidance=engine.get("limiting_guidance", []),
            health_habits=engine.get("health_habits", []),
            focus_areas=engine.get("focus_areas", []),
            normal_parameters=engine.get("normal_parameters", []),
            caution_flags=engine.get("caution_flags", []),
            triggered_rules=engine.get("triggered_rules", []),
            meal_plan=engine.get("meal_plan", {}),
            personalization_summary=(
                "Upload and analyse a health report to generate "
                "report-based dietary guidance."
            ),
                        guidance_message=(
                "No report is currently available. The system will "
                "generate dietary guidance after report analysis."
            ),
            schedule=build_daily_diet({})
        )

    parameter_analysis = data.get("parameter_analysis") or {}
    if not isinstance(parameter_analysis, dict):
        parameter_analysis = {}

    patient_info = data.get("patient_info") or {}
    if not isinstance(patient_info, dict):
        patient_info = {}

    engine = build_personalized_diet(parameter_analysis)

    meal_plan = engine.get("meal_plan") or {
        "Breakfast": "A balanced breakfast with whole grains and a suitable protein source",
        "Lunch": "A balanced meal with vegetables, grains and a suitable protein source",
        "Snack": "A simple snack such as fruit or another suitable option",
        "Dinner": "A balanced meal with vegetables, grains and a suitable protein source"
    }

    return render_template(
        "diet.html",
        report_type=data.get("report_type") or "Laboratory Report",
        patient_info=patient_info,
        report_name=data.get("report_name") or "Uploaded Report",
        analysis_date=data.get("analysis_date") or "Not Available",
        parameter_analysis=parameter_analysis,
        dietary_guidance=engine.get("dietary_guidance", []),
        limiting_guidance=engine.get("limiting_guidance", []),
        health_habits=engine.get("health_habits", []),
        focus_areas=engine.get("focus_areas", []),
        normal_parameters=engine.get("normal_parameters", []),
        caution_flags=engine.get("caution_flags", []),
        triggered_rules=engine.get("triggered_rules", []),
        meal_plan=meal_plan,
        personalization_summary=engine.get(
            "personalization_summary",
            "Guidance is based on the available report parameters."
        ),
                guidance_message=engine.get(
            "guidance_message",
            "General educational guidance based on the available report data."
        ),
        schedule=build_daily_diet(parameter_analysis)
    )


# ============================================================
# PRECAUTIONS
# ============================================================

@app.route("/precautions")
def precautions():
    data = get_analysis_data(session.get("analysis_id")) or {}
    parameter_analysis = data.get("parameter_analysis") or {}
    if not isinstance(parameter_analysis, dict):
        parameter_analysis = {}

    return render_template(
        "precautions.html",
        report_name=data.get("report_name", "No Report Available"),
        analysis_date=data.get("analysis_date", "Not Available"),
        schedule=build_daily_precautions(parameter_analysis)
    )


# ============================================================
# TRENDS
# ============================================================

@app.route("/trends")
def trends():
    trend_parameters = []

    for report in report_history:
        parameters = report.get("parameters", {})

        if not isinstance(parameters, dict):
            continue

        for parameter_name in parameters:
            if parameter_name not in trend_parameters:
                trend_parameters.append(parameter_name)

    requested_parameter = request.args.get("parameter", "").strip()

    if requested_parameter and requested_parameter in trend_parameters:
        selected_parameter = requested_parameter
    elif trend_parameters:
        selected_parameter = trend_parameters[0]
    else:
        selected_parameter = ""

    trend_history = []

    for report in report_history:
        parameters = report.get("parameters", {})

        if not isinstance(parameters, dict) or selected_parameter not in parameters:
            continue

        parameter = parameters.get(selected_parameter, {})
        numeric_value = parameter.get("numeric_value")

        if numeric_value is None:
            numeric_value = number_from_text(parameter.get("value"))

        if numeric_value is None:
            continue

        status = parameter.get("status", "Not Available")
        unit = parameter.get("unit", "")
        display_value = parameter.get("value", numeric_value)

        value_display = f"{display_value} {unit}" if unit else str(display_value)

        report_date = report.get("report_date", "Not Available")
        parsed_date = parse_report_datetime(report_date)

        trend_history.append({
            "report_date": report_date,
            "report_date_display": report.get(
                "report_date_display",
                format_report_date(report_date)
            ),
            "report_name": report.get("report_name", "Uploaded Report"),
            "value": numeric_value,
            "value_display": value_display,
            "unit": unit,
            "status": status,
            "status_class": status_css_class(status),
            "sort_key": parsed_date.isoformat() if parsed_date else ""
        })

    trend_history.sort(key=lambda item: (item["sort_key"], item["report_name"]))

    chart_points = []
    chart_polyline = ""
    chart_dates = []
    y_axis_labels = []

    if trend_history:
        values = [item["value"] for item in trend_history]

        minimum_value = min(values)
        maximum_value = max(values)

        if minimum_value == maximum_value:
            padding = abs(minimum_value) * 0.10 if minimum_value != 0 else 1
            chart_min = minimum_value - padding
            chart_max = maximum_value + padding
        else:
            padding = (maximum_value - minimum_value) * 0.10
            chart_min = minimum_value - padding
            chart_max = maximum_value + padding

        left = 40
        right = 640
        top = 25
        bottom = 250

        usable_width = right - left
        usable_height = bottom - top

        count = len(trend_history)

        for index, item in enumerate(trend_history):
            if count == 1:
                x = left + usable_width / 2
            else:
                x = left + (usable_width * index / (count - 1))

            ratio = (item["value"] - chart_min) / (chart_max - chart_min)
            y = bottom - (ratio * usable_height)

            chart_points.append({
                "x": round(x, 2),
                "y": round(y, 2),
                "value": item["value"],
                "value_display": item["value_display"]
            })

            chart_dates.append(item["report_date_display"])

        chart_polyline = " ".join(
            f'{point["x"]},{point["y"]}'
            for point in chart_points
        )

        for index in range(6):
            ratio = index / 5
            value = chart_max - ((chart_max - chart_min) * ratio)

            if abs(value) >= 100:
                label = f"{value:.0f}"
            elif abs(value) >= 10:
                label = f"{value:.1f}"
            else:
                label = f"{value:.2f}"

            y_axis_labels.append(label)

    latest_value_display = "Not Available"
    previous_value_display = "Not Available"

    if trend_history:
        latest_value_display = trend_history[-1]["value_display"]

    if len(trend_history) >= 2:
        previous_value_display = trend_history[-2]["value_display"]

    table_history = list(reversed(trend_history))

    return render_template(
        "trends.html",
        trend_parameters=trend_parameters,
        selected_parameter=selected_parameter,
        trend_history=table_history,
        chart_points=chart_points,
        chart_polyline=chart_polyline,
        chart_dates=chart_dates,
        y_axis_labels=y_axis_labels,
        latest_value_display=latest_value_display,
        previous_value_display=previous_value_display,
        reports_available=len(trend_history),
        has_trend_data=bool(trend_history)
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    app.run(debug=True)