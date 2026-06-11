#!/usr/bin/env python3
"""Deterministic basic checks for fission product yield tables.

The script intentionally uses only the Python standard library so it can run in
restricted environments. It performs numerical checks; physical applicability
must still be judged by the calling agent.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


YIELD_ALIASES = (
    "yield",
    "y",
    "fy",
    "fpy",
    "yld",
    "yi",
    "yield_value",
    "fission_yield",
    "mass_yield",
    "independent_yield",
    "cumulative_yield",
    "iy",
    "cy",
)
UNCERTAINTY_ALIASES = (
    "uncertainty",
    "unc",
    "dy",
    "dyi",
    "sigma",
    "std",
    "error",
    "yield_unc",
    "yield_error",
    "unc_yield",
)
NUCLIDE_ALIASES = ("nuclide", "isotope", "product", "zaid", "zafp", "nucleus")
A_ALIASES = ("a", "mass", "mass_number")
Z_ALIASES = ("z", "charge", "atomic_number")
FORMAT_CHOICES = ("auto", "csv", "tsv", "whitespace", "json", "jsonl", "endf6-fpy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic numerical checks on fission product yield data."
    )
    parser.add_argument("data_file", help="Fission yield data file")
    parser.add_argument(
        "--input-format",
        default="auto",
        choices=FORMAT_CHOICES,
        help="Input adapter to use; auto detects common extensions and ENDF-6-like records",
    )
    parser.add_argument("--delimiter", default="auto", choices=["auto", "comma", "tab", "space"])
    parser.add_argument("--yield-col", default=None, help="Yield column name")
    parser.add_argument("--uncertainty-col", default=None, help="Uncertainty column name")
    parser.add_argument("--a-col", default=None, help="Mass number column name, optional")
    parser.add_argument("--z-col", default=None, help="Atomic number column name, optional")
    parser.add_argument("--nuclide-col", default=None, help="Nuclide identifier column name, optional")
    parser.add_argument(
        "--complete-independent",
        action="store_true",
        help="Apply independent complete-distribution normalization check",
    )
    parser.add_argument(
        "--yield-scale",
        default="auto",
        choices=["auto", "fraction", "percent"],
        help="Yield normalization scale for complete independent distributions",
    )
    parser.add_argument(
        "--relative-uncertainty-warn",
        type=float,
        default=10.0,
        help="Warn when a positive major yield has relative uncertainty above this value",
    )
    parser.add_argument(
        "--major-yield-threshold",
        type=float,
        default=None,
        help="Absolute threshold for major yields; default is 1 percent of max positive yield",
    )
    parser.add_argument("--covariance", default=None, help="Optional CSV/TSV covariance matrix")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    return parser.parse_args()


def canonical_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower().strip()).strip("_")


def detect_input_format(path: str, requested: str) -> str:
    if requested != "auto":
        return requested
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        return "json"
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if ext in (".tsv",):
        return "tsv"
    if ext in (".csv",):
        return "csv"
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        sample_lines = [handle.readline() for _ in range(20)]
    sample = "".join(sample_lines)
    if looks_like_endf6(sample_lines):
        return "endf6-fpy"
    stripped = sample.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return "json"
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    if stripped.startswith('"') or "\t" in sample:
        return "tsv" if "\t" in sample and "," not in first_line else "csv"
    return "whitespace" if "," not in first_line else "csv"


def detect_delimiter(path: str, requested: str) -> Optional[str]:
    if requested == "comma":
        return ","
    if requested == "tab":
        return "\t"
    if requested == "space":
        return None
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t ;")
        if dialect.delimiter == " ":
            return None
        return dialect.delimiter
    except csv.Error:
        if "\t" in sample:
            return "\t"
        return ","


def stringify_rows(records: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], List[str]]:
    rows = [{str(k): "" if v is None else str(v) for k, v in record.items()} for record in records]
    fieldnames = sorted({key for row in rows for key in row.keys()})
    return rows, fieldnames


def flatten_json_record(record: Dict[str, Any]) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flattened[f"{key}_{nested_key}"] = nested_value
        else:
            flattened[key] = value
    return flattened


def records_from_json_value(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("data", "rows", "yields", "records", "products", "values"):
            if isinstance(data.get(key), list):
                return records_from_json_value(data[key])
        records = []
        for key, value in data.items():
            if isinstance(value, dict):
                record = {"nuclide": key}
                record.update(flatten_json_record(value))
                records.append(record)
            elif isinstance(value, (int, float, str)) or value is None:
                records.append({"nuclide": key, "yield": value})
        if records:
            return records
    if isinstance(data, list):
        records = []
        for item in data:
            if isinstance(item, dict):
                records.append(flatten_json_record(item))
            elif isinstance(item, list) and len(item) >= 2:
                record = {"nuclide": item[0], "yield": item[1]}
                if len(item) >= 3:
                    record["uncertainty"] = item[2]
                records.append(record)
        if records:
            return records
    raise ValueError(
        "JSON input must be records, a dict containing data/rows/yields/records, "
        "or a mapping like {nuclide: yield}"
    )


def read_json_table(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return stringify_rows(records_from_json_value(data))


def read_jsonl_table(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            item = json.loads(stripped)
            if not isinstance(item, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            records.append(flatten_json_record(item))
    return stringify_rows(records)


def read_delimited_table(path: str, delimiter_request: str) -> Tuple[List[Dict[str, str]], List[str]]:
    delimiter = detect_delimiter(path, delimiter_request)
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        if delimiter is None:
            lines = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]
            if not lines:
                return [], []
            header = lines[0].split()
            rows = []
            for line in lines[1:]:
                values = line.split()
                rows.append({header[i]: values[i] if i < len(values) else "" for i in range(len(header))})
            return rows, header
        reader = csv.DictReader((row for row in handle if not row.lstrip().startswith("#")), delimiter=delimiter)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def parse_endf_float(value: str) -> Optional[float]:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    # ENDF-6 omits the E in scientific notation, e.g. " 9.223500+4".
    if re.search(r"[+-]\d+$", text) and "e" not in text.lower():
        for index in range(len(text) - 1, 0, -1):
            if text[index] in "+-" and text[index - 1].isdigit():
                try:
                    return float(text[:index] + "e" + text[index:])
                except ValueError:
                    break
    return None


def parse_endf_int(value: str) -> Optional[int]:
    parsed = parse_endf_float(value)
    if parsed is None or not math.isfinite(parsed):
        return None
    return int(round(parsed))


def endf_data_fields(line: str) -> List[str]:
    padded = line.rstrip("\n").ljust(66)
    return [padded[index : index + 11] for index in range(0, 66, 11)]


def endf_tail(line: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    padded = line.rstrip("\n").ljust(80)
    try:
        mf = int(padded[70:72])
        mt = int(padded[72:75])
    except ValueError:
        return None, None, None
    try:
        mat = int(padded[66:70])
    except ValueError:
        mat = None
    return mat, mf, mt


def looks_like_endf6(lines: Sequence[str]) -> bool:
    hits = 0
    for line in lines:
        if len(line) < 75:
            continue
        _, mf, mt = endf_tail(line)
        if mf == 8 and mt in (454, 459):
            hits += 1
    return hits > 0


def zafp_to_z_a(zafp: int) -> Tuple[Optional[int], Optional[int]]:
    if zafp <= 0:
        return None, None
    z = zafp // 1000
    a = zafp - z * 1000
    return z, a


def read_endf6_fpy_table(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read a lightweight subset of ENDF-6 MF=8 MT=454/459 FPY LIST records.

    This adapter is intentionally conservative: it extracts LIST records whose
    payload length is a multiple of four and interprets each quadruplet as
    ZAFP, FPS, yield, uncertainty. It is suitable for deterministic screening,
    not a complete ENDF validator.
    """

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    rows: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        mat, mf, mt = endf_tail(line)
        if mf != 8 or mt not in (454, 459):
            index += 1
            continue
        fields = endf_data_fields(line)
        c1 = parse_endf_float(fields[0])
        l1 = parse_endf_int(fields[2])
        npl = parse_endf_int(fields[4])
        n2 = parse_endf_int(fields[5])
        if npl is None or npl <= 0 or npl % 4 != 0:
            index += 1
            continue
        data: List[float] = []
        data_lines = int(math.ceil(npl / 6.0))
        for data_line in lines[index + 1 : index + 1 + data_lines]:
            _, data_mf, data_mt = endf_tail(data_line)
            if data_mf != mf or data_mt != mt:
                continue
            for field in endf_data_fields(data_line):
                value = parse_endf_float(field)
                if value is not None:
                    data.append(value)
        if len(data) >= npl:
            for offset in range(0, npl, 4):
                zafp = int(round(data[offset]))
                z, a = zafp_to_z_a(zafp)
                rows.append(
                    {
                        "source_format": "endf6-fpy",
                        "yield_type": "independent" if mt == 454 else "cumulative",
                        "mat": mat,
                        "mt": mt,
                        "energy": c1,
                        "interpolation_flag": l1,
                        "zafp": zafp,
                        "z": z,
                        "a": a,
                        "state": data[offset + 1],
                        "yield": data[offset + 2],
                        "uncertainty": data[offset + 3],
                    }
                )
            index += data_lines + 1
        else:
            index += 1
    if not rows:
        raise ValueError("No MF=8 MT=454/459 FPY LIST records found in ENDF-6 input")
    return stringify_rows(rows)


def read_table(path: str, input_format: str, delimiter_request: str) -> Tuple[List[Dict[str, str]], List[str], Dict[str, Any]]:
    selected_format = detect_input_format(path, input_format)
    if selected_format == "json":
        rows, fieldnames = read_json_table(path)
    elif selected_format == "jsonl":
        rows, fieldnames = read_jsonl_table(path)
    elif selected_format == "csv":
        rows, fieldnames = read_delimited_table(path, "comma")
    elif selected_format == "tsv":
        rows, fieldnames = read_delimited_table(path, "tab")
    elif selected_format == "whitespace":
        rows, fieldnames = read_delimited_table(path, "space")
    elif selected_format == "endf6-fpy":
        rows, fieldnames = read_endf6_fpy_table(path)
    else:
        rows, fieldnames = read_delimited_table(path, delimiter_request)
    return rows, fieldnames, {"input_format": selected_format}


def canonical_map(fieldnames: Sequence[str]) -> Dict[str, str]:
    return {canonical_name(name): name for name in fieldnames}


def find_column(fieldnames: Sequence[str], explicit: Optional[str], aliases: Sequence[str]) -> Optional[str]:
    if explicit:
        if explicit in fieldnames:
            return explicit
        lowered = canonical_map(fieldnames)
        return lowered.get(canonical_name(explicit))
    lowered = canonical_map(fieldnames)
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    return parse_endf_float(text)


def row_label(index: int, row: Dict[str, str], nuclide_col: Optional[str]) -> str:
    label = f"row {index}"
    if nuclide_col and row.get(nuclide_col):
        label += f" ({row[nuclide_col]})"
    return label


def summarize_numbers(
    rows: List[Dict[str, str]],
    yield_col: Optional[str],
    uncertainty_col: Optional[str],
    nuclide_col: Optional[str],
    relative_uncertainty_warn: float,
    major_yield_threshold: Optional[float],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "row_count": len(rows),
        "yield_column": yield_col,
        "uncertainty_column": uncertainty_col,
        "yield": {},
        "uncertainty": {},
    }
    if not yield_col:
        result["yield"]["status"] = "BLOCKER"
        result["yield"]["message"] = "No yield column found"
        return result

    yields: List[Tuple[int, float]] = []
    missing = []
    non_finite = []
    negative = []
    for i, row in enumerate(rows, start=2):
        value = parse_float(row.get(yield_col))
        if value is None:
            missing.append(row_label(i, row, nuclide_col))
            continue
        if not math.isfinite(value):
            non_finite.append(row_label(i, row, nuclide_col))
            continue
        if value < 0:
            negative.append((row_label(i, row, nuclide_col), value))
        yields.append((i, value))

    values = [value for _, value in yields]
    result["yield"].update(
        {
            "parsed_count": len(values),
            "missing_count": len(missing),
            "non_finite_count": len(non_finite),
            "negative_count": len(negative),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "sum": sum(values) if values else 0.0,
            "negative_examples": negative[:10],
            "missing_examples": missing[:10],
            "non_finite_examples": non_finite[:10],
            "status": "FAIL" if negative or non_finite else "PASS",
        }
    )

    if not uncertainty_col:
        result["uncertainty"]["status"] = "INFO"
        result["uncertainty"]["message"] = "No uncertainty column supplied or detected"
        return result

    uncertainties: List[float] = []
    unc_missing = []
    unc_non_finite = []
    unc_negative = []
    high_relative = []
    max_positive_yield = max((value for value in values if value > 0), default=0.0)
    major_threshold = (
        major_yield_threshold
        if major_yield_threshold is not None
        else 0.01 * max_positive_yield
    )
    for i, row in enumerate(rows, start=2):
        unc = parse_float(row.get(uncertainty_col))
        y = parse_float(row.get(yield_col))
        if unc is None:
            unc_missing.append(row_label(i, row, nuclide_col))
            continue
        if not math.isfinite(unc):
            unc_non_finite.append(row_label(i, row, nuclide_col))
            continue
        if unc < 0:
            unc_negative.append((row_label(i, row, nuclide_col), unc))
        uncertainties.append(unc)
        if y is not None and math.isfinite(y) and y > major_threshold and y > 0:
            rel = unc / y
            if rel > relative_uncertainty_warn:
                high_relative.append((row_label(i, row, nuclide_col), rel, y, unc))

    status = "FAIL" if unc_negative or unc_non_finite else ("WARN" if high_relative else "PASS")
    result["uncertainty"].update(
        {
            "parsed_count": len(uncertainties),
            "missing_count": len(unc_missing),
            "non_finite_count": len(unc_non_finite),
            "negative_count": len(unc_negative),
            "min": min(uncertainties) if uncertainties else None,
            "max": max(uncertainties) if uncertainties else None,
            "high_relative_examples": high_relative[:10],
            "negative_examples": unc_negative[:10],
            "missing_examples": unc_missing[:10],
            "non_finite_examples": unc_non_finite[:10],
            "status": status,
        }
    )
    return result


def normalization_check(total: float, scale: str, apply_check: bool) -> Dict[str, Any]:
    if not apply_check:
        return {"status": "NA", "message": "Not marked as complete independent distribution"}
    if scale == "auto":
        scale = "percent" if total > 20 else "fraction"
    expected = 200.0 if scale == "percent" else 2.0
    deviation = total - expected
    rel = abs(deviation) / expected if expected else math.inf
    if rel <= 0.02:
        status = "PASS"
    elif rel <= 0.10:
        status = "WARN"
    else:
        status = "FAIL"
    return {
        "status": status,
        "scale": scale,
        "total": total,
        "expected": expected,
        "absolute_deviation": deviation,
        "relative_deviation": rel,
    }


def read_matrix(path: str) -> List[List[float]]:
    delimiter = detect_delimiter(path, "auto")
    matrix: List[List[float]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split() if delimiter is None else next(csv.reader([stripped], delimiter=delimiter))
            row = [parse_float(part) for part in parts]
            if any(value is None for value in row):
                raise ValueError(f"Non-numeric covariance row: {stripped}")
            matrix.append([float(value) for value in row if value is not None])
    return matrix


def jacobi_min_eigenvalue(matrix: List[List[float]], max_iter: int = 100) -> Optional[float]:
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix):
        return None
    a = [row[:] for row in matrix]
    for _ in range(max_iter * n * n):
        p, q = 0, 1 if n > 1 else 0
        max_off = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                value = abs(a[i][j])
                if value > max_off:
                    max_off = value
                    p, q = i, j
        if max_off < 1e-12:
            break
        if a[p][p] == a[q][q]:
            angle = math.pi / 4
        else:
            angle = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
        c = math.cos(angle)
        s = math.sin(angle)
        app = c * c * a[p][p] - 2 * s * c * a[p][q] + s * s * a[q][q]
        aqq = s * s * a[p][p] + 2 * s * c * a[p][q] + c * c * a[q][q]
        a[p][p] = app
        a[q][q] = aqq
        a[p][q] = 0.0
        a[q][p] = 0.0
        for r in range(n):
            if r == p or r == q:
                continue
            arp = c * a[r][p] - s * a[r][q]
            arq = s * a[r][p] + c * a[r][q]
            a[r][p] = a[p][r] = arp
            a[r][q] = a[q][r] = arq
    return min(a[i][i] for i in range(n))


def covariance_check(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {"status": "NA", "message": "No covariance matrix supplied"}
    matrix = read_matrix(path)
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix):
        return {"status": "FAIL", "message": "Covariance matrix must be square", "size": n}
    max_asym = 0.0
    for i in range(n):
        for j in range(n):
            max_asym = max(max_asym, abs(matrix[i][j] - matrix[j][i]))
    min_diag = min(matrix[i][i] for i in range(n))
    min_eig = jacobi_min_eigenvalue(matrix) if n <= 200 else None
    status = "PASS"
    messages = []
    if max_asym > 1e-8:
        status = "FAIL"
        messages.append("matrix is not symmetric within 1e-8")
    if min_diag < 0:
        status = "FAIL"
        messages.append("negative diagonal variance")
    if min_eig is not None:
        if min_eig < -1e-8:
            status = "FAIL"
            messages.append("large negative eigenvalue")
        elif min_eig < 0 and status != "FAIL":
            status = "WARN"
            messages.append("small negative eigenvalue")
    else:
        messages.append("eigenvalue check skipped for matrix larger than 200x200")
        if status == "PASS":
            status = "INFO"
    return {
        "status": status,
        "size": n,
        "max_asymmetry": max_asym,
        "min_diagonal": min_diag,
        "min_eigenvalue": min_eig,
        "messages": messages,
    }


def overall_status(items: Iterable[Dict[str, Any]]) -> str:
    statuses = [item.get("status") for item in items]
    for status in ("FAIL", "BLOCKER", "WARN", "INFO"):
        if status in statuses:
            return status
    return "PASS"


def render_markdown(result: Dict[str, Any]) -> str:
    lines = [
        "# FPY Basic Audit",
        "",
        f"- File: `{result['file']}`",
        f"- Input format: `{result['input_format']}`",
        f"- Rows: {result['rows']}",
        f"- Overall status: `{result['overall_status']}`",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    y = result["checks"]["yield"]
    lines.append(
        "| NUM-001 finite non-negative yields | "
        f"`{y.get('status')}` | column `{result['columns'].get('yield')}`, "
        f"parsed {y.get('parsed_count', 0)}, negatives {y.get('negative_count', 0)}, "
        f"non-finite {y.get('non_finite_count', 0)}, min {y.get('min')}, max {y.get('max')} |"
    )
    u = result["checks"]["uncertainty"]
    lines.append(
        "| NUM-002 uncertainty validity | "
        f"`{u.get('status')}` | column `{result['columns'].get('uncertainty')}`, "
        f"negatives {u.get('negative_count', 0)}, non-finite {u.get('non_finite_count', 0)}, "
        f"high-relative examples {len(u.get('high_relative_examples', []))} |"
    )
    n = result["checks"]["normalization"]
    lines.append(
        "| NUM-003 normalization | "
        f"`{n.get('status')}` | total {n.get('total')}, expected {n.get('expected')}, "
        f"scale {n.get('scale', 'NA')} |"
    )
    c = result["checks"]["covariance"]
    lines.append(
        "| NUM-004 covariance validity | "
        f"`{c.get('status')}` | size {c.get('size', 'NA')}, max asymmetry {c.get('max_asymmetry', 'NA')}, "
        f"min eigenvalue {c.get('min_eigenvalue', 'NA')} |"
    )

    examples = []
    if y.get("negative_examples"):
        examples.append(("Negative yield examples", y["negative_examples"]))
    if y.get("non_finite_examples"):
        examples.append(("Non-finite yield examples", y["non_finite_examples"]))
    if u.get("negative_examples"):
        examples.append(("Negative uncertainty examples", u["negative_examples"]))
    if u.get("high_relative_examples"):
        examples.append(("High relative uncertainty examples", u["high_relative_examples"]))
    if examples:
        lines.extend(["", "## Examples"])
        for title, values in examples:
            lines.append(f"- {title}: `{values}`")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    rows, fieldnames, table_meta = read_table(args.data_file, args.input_format, args.delimiter)
    column_map = canonical_map(fieldnames)
    yield_col = find_column(fieldnames, args.yield_col, YIELD_ALIASES)
    uncertainty_col = find_column(fieldnames, args.uncertainty_col, UNCERTAINTY_ALIASES)
    nuclide_col = find_column(fieldnames, args.nuclide_col, NUCLIDE_ALIASES)
    a_col = find_column(fieldnames, args.a_col, A_ALIASES)
    z_col = find_column(fieldnames, args.z_col, Z_ALIASES)
    numeric = summarize_numbers(
        rows,
        yield_col,
        uncertainty_col,
        nuclide_col,
        args.relative_uncertainty_warn,
        args.major_yield_threshold,
    )
    total = numeric.get("yield", {}).get("sum", 0.0)
    normalization = normalization_check(total, args.yield_scale, args.complete_independent)
    covariance = covariance_check(args.covariance)
    result = {
        "file": args.data_file,
        "input_format": table_meta["input_format"],
        "rows": len(rows),
        "fieldnames": fieldnames,
        "columns": {
            "yield": yield_col,
            "uncertainty": uncertainty_col,
            "nuclide": nuclide_col,
            "a": a_col,
            "z": z_col,
            "available": column_map,
        },
        "checks": {
            "yield": numeric["yield"],
            "uncertainty": numeric["uncertainty"],
            "normalization": normalization,
            "covariance": covariance,
        },
    }
    result["overall_status"] = overall_status(result["checks"].values())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result))
    return 1 if result["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"fpy_basic_audit.py: error: {exc}", file=sys.stderr)
        raise SystemExit(2)
