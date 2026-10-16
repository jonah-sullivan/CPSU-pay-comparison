"""Extract current, March 2027, March 2028 and March 2029 maximum pay from the APS
pay calculator.

Output columns:
Agency, Agency name, APS1-2026, APS1-2027, APS1-2028, APS1-2029, APS2-2026, ... EL2-2029

The script processes agency worksheets, selects the top increment for each requested
classification, and writes one agency per row (named by worksheet). It uses only
Python's standard library, so no package installation is required.

Input and output default to the script's own folder, so it can be run from anywhere:
    python extract_current_and_march_2029_pay.py

Optional arguments:
    python extract_current_and_march_2029_pay.py \
        --input "APS Bargaining Pay Calculator.xlsx" \
        --output "aps_pay_2026_2029.csv"
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN_NS, "r": OFFICE_REL_NS}
GRADES = ("APS1", "APS2", "APS3", "APS4", "APS5", "APS6", "EL1", "EL2")
# Column suffix for the current pay rate ("Pay Rate as at 13 October 2026").
CURRENT_YEAR = "2026"
# Later pay rates: (column suffix, header text to find, fallback offset from the
# current pay column if the header is not found).
LATER_PERIODS = (
    ("2027", "march 2027", 1),
    ("2028", "march 2028", 3),
    ("2029", "march 2029", 4),
)
EXCLUDED_SHEETS = {
    "Table of Contents",
    "Impacts Pay Offer",
    "Impacts Pay Fragmentation",
    "Impacts Salary Advancement",
}
# Agencies that use their own classification names. Each prefix is treated as the
# equivalent APS/EL classification, e.g. DPS "PSL3" -> "APS3", NGA "NGA Level 3" -> "APS3".
CLASSIFICATION_ALIASES = {
    "DPS": (("PSL", "APS"), ("PEL", "EL")),
    "NGA": (("NGA LEVEL", "APS"),),
}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def column_number(cell_reference: str) -> int:
    letters = re.match(r"[A-Z]+", cell_reference.upper()).group(0)
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return number


def number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    text = str(value).strip().replace("$", "").replace(",", "")
    try:
        result = float(text)
    except ValueError:
        return None
    return int(result) if result.is_integer() else result


def grade_from_value(value, aliases=()):
    """Recognise APS/EL classifications and increments, e.g. APS 4 or EL2.5."""
    text = clean(value).upper()
    for prefix, replacement in aliases:
        if text.startswith(prefix):
            text = replacement + text[len(prefix) :]
            break
    match = re.match(r"^APS\s*([1-6])(?:[._\s-]\d+)?$", text)
    if match:
        return "APS" + match.group(1)
    match = re.match(r"^(?:EL|EXECUTIVE\s*LEVEL)\s*([12])(?:[._\s-]\d+)?$", text)
    if match:
        return "EL" + match.group(1)
    compact = re.sub(r"[^A-Z0-9]", "", text)
    for grade in GRADES:
        if compact in {grade, grade + "MAX", grade + "MIN"}:
            return grade
    return None


class XlsxReader:
    """Minimal cached-value XLSX reader using the standard library."""

    def __init__(self, path: Path):
        self.archive = zipfile.ZipFile(path)
        self.shared_strings = self._shared_strings()
        self.sheet_paths = self._sheet_paths()

    def close(self):
        self.archive.close()

    def _shared_strings(self):
        if "xl/sharedStrings.xml" not in self.archive.namelist():
            return []
        root = ET.fromstring(self.archive.read("xl/sharedStrings.xml"))
        return [
            "".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
            for item in root.findall(f"{{{MAIN_NS}}}si")
        ]

    def _sheet_paths(self):
        workbook = ET.fromstring(self.archive.read("xl/workbook.xml"))
        rels = ET.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        relationship_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        paths = {}
        for sheet in workbook.find("m:sheets", NS):
            target = relationship_map[sheet.attrib[f"{{{OFFICE_REL_NS}}}id"]]
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            paths[sheet.attrib["name"]] = target
        return paths

    def rows(self, sheet_name):
        root = ET.fromstring(self.archive.read(self.sheet_paths[sheet_name]))
        for row in root.iter(f"{{{MAIN_NS}}}row"):
            values = {}
            for cell in row.findall(f"{{{MAIN_NS}}}c"):
                col = column_number(cell.attrib.get("r", "A1"))
                kind = cell.attrib.get("t")
                value_node = cell.find(f"{{{MAIN_NS}}}v")
                inline = cell.find(f"{{{MAIN_NS}}}is")
                raw = value_node.text if value_node is not None else None
                if kind == "s" and raw is not None:
                    value = self.shared_strings[int(raw)]
                elif kind == "inlineStr" and inline is not None:
                    value = "".join(
                        node.text or "" for node in inline.iter(f"{{{MAIN_NS}}}t")
                    )
                elif kind in ("str", "b"):
                    value = raw
                else:
                    value = number(raw)
                values[col] = value
            if values:
                yield int(row.attrib.get("r", "0")), values


def find_source_table(rows):
    """Find the left-hand appendix table and its relevant columns."""
    candidates = []
    for row_number, cells in rows:
        text = {col: clean(value).casefold() for col, value in cells.items()}
        agency_cols = [col for col, value in text.items() if value == "agency"]
        class_cols = [col for col, value in text.items() if value == "classification"]
        max_cols = [col for col, value in text.items() if "max/min" in value]
        current_cols = [
            col
            for col, value in text.items()
            if "pay rate" in value and ("now" in value or "13 october 2026" in value)
        ]
        period_cols = {
            year: [col for col, value in text.items() if header in value]
            for year, header, _ in LATER_PERIODS
        }

        for class_col in class_cols:
            # The source appendix is the left-hand table and includes an Agency column.
            left_agency = [col for col in agency_cols if col < class_col]
            nearby_max = [col for col in max_cols if class_col < col <= class_col + 4]
            nearby_current = [
                col for col in current_cols if class_col < col <= class_col + 10
            ]
            if class_col <= 5 and left_agency and nearby_max and nearby_current:
                current_col = min(nearby_current)
                periods = {}
                fallback_years = []
                for year, _, offset in LATER_PERIODS:
                    nearby = [
                        col
                        for col in period_cols[year]
                        if current_col < col <= class_col + 12
                    ]
                    if nearby:
                        periods[year] = min(nearby)
                    else:
                        periods[year] = current_col + offset
                        fallback_years.append(year)
                candidates.append(
                    {
                        "header_row": row_number,
                        "agency": max(left_agency),
                        "classification": class_col,
                        "maxmin": min(nearby_max),
                        "current": current_col,
                        "periods": periods,
                        "fallback_years": fallback_years,
                    }
                )
    return (
        min(candidates, key=lambda item: item["classification"]) if candidates else None
    )


def extract_sheet(sheet_name, rows):
    table = find_source_table(rows)
    if not table:
        return None, ["No source appendix table found"]

    warnings = []
    # The agency's full name sits above the appendix, in column C of row 2
    # (column B has the short name, e.g. "ABS" / "Australian Bureau of Statistics").
    full_name = next(
        (
            clean(cells[3])
            for row_number, cells in rows
            if row_number < table["header_row"] and clean(cells.get(3))
        ),
        "",
    )
    if not full_name:
        warnings.append("Agency full name not found")
    aliases = CLASSIFICATION_ALIASES.get(sheet_name, ())
    for prefix, replacement in aliases:
        warnings.append(
            f"Classification alias applied: {prefix} treated as {replacement}"
        )
    for year in table["fallback_years"]:
        warnings.append(
            f"March {year} header not found; assumed column {table['periods'][year]}"
        )

    # Collect every pay point per grade, then take the top increment (highest current
    # pay). The Max/Min marker is unreliable (sometimes missing or misplaced), so it is
    # only used as a cross-check.
    pay_points = {grade: [] for grade in GRADES}
    last_grade = None
    for row_number, cells in rows:
        if row_number <= table["header_row"]:
            continue

        explicit_grade = grade_from_value(cells.get(table["classification"]), aliases)
        if explicit_grade:
            last_grade = explicit_grade

        # The increment is normally two columns after Max/Min and is particularly
        # reliable on rows where merged classification cells are blank.
        increment = cells.get(table["maxmin"] + 2)
        grade = grade_from_value(increment, aliases) or last_grade
        current = number(cells.get(table["current"]))
        if grade not in GRADES or current is None:
            continue
        later = [number(cells.get(col)) for col in table["periods"].values()]
        missing = [
            year for year, value in zip(table["periods"], later) if value is None
        ]
        if missing:
            warnings.append(
                f"Row {row_number}: missing March {', '.join(missing)} pay for {grade}"
            )
            continue

        is_max = "MAX" in clean(cells.get(table["maxmin"])).upper()
        pay_points[grade].append(
            ((current, *later), row_number, clean(increment), is_max)
        )

    extracted = {}
    for grade, points in pay_points.items():
        if not points:
            warnings.append(f"Missing {grade} maximum")
            continue
        values, row_number, increment, is_max = max(points)
        extracted[grade] = values
        if not any(point[3] for point in points):
            warnings.append(
                f"{grade}: no Max marker; used top increment {increment} (row {row_number})"
            )
        elif not is_max:
            warnings.append(
                f"{grade}: top increment {increment} (row {row_number}) is not marked Max"
            )

    return (sheet_name, full_name, extracted), warnings


def main():
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / "APS Bargaining Pay Calculator.xlsx",
        help="Path to APS Bargaining Pay Calculator.xlsx",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "aps_pay_2026_2029.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--warnings",
        type=Path,
        default=script_dir / "aps_pay_2026_2029_warnings.csv",
        help="Warnings CSV path",
    )
    args = parser.parse_args()

    years = [CURRENT_YEAR, *(year for year, _, _ in LATER_PERIODS)]
    headers = ["Agency", "Agency name"]
    for grade in GRADES:
        headers.extend(f"{grade}-{year}" for year in years)

    output_rows = []
    warning_rows = []
    reader = XlsxReader(args.input)
    try:
        for sheet_name in reader.sheet_paths:
            if sheet_name in EXCLUDED_SHEETS:
                continue
            result, warnings = extract_sheet(sheet_name, list(reader.rows(sheet_name)))
            if result is None:
                warning_rows.extend(
                    {"Sheet": sheet_name, "Warning": item} for item in warnings
                )
                continue

            agency_name, full_name, pay = result
            row = {header: "" for header in headers}
            row["Agency"] = agency_name
            row["Agency name"] = full_name
            for grade in GRADES:
                if grade in pay:
                    for year, value in zip(years, pay[grade]):
                        row[f"{grade}-{year}"] = value
            output_rows.append(row)
            warning_rows.extend(
                {"Sheet": sheet_name, "Warning": item} for item in warnings
            )
    finally:
        reader.close()

    output_rows.sort(key=lambda row: row["Agency"].casefold())
    warning_rows.sort(key=lambda row: (row["Sheet"].casefold(), row["Warning"]))

    with args.output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(output_rows)

    with args.warnings.open("w", newline="", encoding="utf-8-sig") as warning_file:
        writer = csv.DictWriter(warning_file, fieldnames=["Sheet", "Warning"])
        writer.writeheader()
        writer.writerows(warning_rows)

    complete = sum(
        all(row[f"{grade}-{year}"] != "" for grade in GRADES for year in years)
        for row in output_rows
    )
    print(f"Created {args.output} with {len(output_rows)} agency rows")
    print(f"Rows containing all eight requested grades: {complete}")
    print(f"Created {args.warnings} with {len(warning_rows)} review warnings")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
