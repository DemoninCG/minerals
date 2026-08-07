"""Merge downloaded Mindat fields into the local IMA mineral table by name.

Reads raw records created by ``main.py`` from
``mindat_export/ima_geomaterial_batches``. By default, output contains only
minerals with a Mindat name match; the original ``IMA_data.csv`` is never
modified. Name comparison normalizes case, Unicode accents, punctuation, and
spacing, so entries such as ``D'ansite`` match Mindat's punctuated spelling.

The 30 unmatched rows are the pure native-element names in the source table;
Mindat represents these as mineral species with different names, so they are
intentionally excluded rather than guessed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "IMA_data.csv"
DEFAULT_BATCH_DIRECTORY = ROOT / "mindat_export" / "ima_geomaterial_batches"
DEFAULT_OUTPUT = ROOT / "IMA_data_with_mindat.csv"
DEFAULT_REPORT = ROOT / "mindat_merge_report.json"
MINDAT_API_ROOT = "https://api.mindat.org"
CERIUM_MINDAT_ID = 46643

# Mindat record fields most useful for grouping, filtering, node coloring, and
# hover/detail panels. The source dataset's columns are retained unchanged.
MINDAT_COLUMNS = [
    "Mindat ID",
    "Mindat Long ID",
    "Mindat GUID",
    "Mindat Updated",
    "Mindat Entry Type",
    "Mindat Entry Type Text",
    "Mindat Formula",
    "Mindat Formula Note",
    "Mindat IMA Formula",
    "Mindat IMA Status",
    "Mindat IMA Notes",
    "Mindat Description",
    "Mindat Elements",
    "Mindat Significant Elements",
    "Mindat Key Elements",
    "Mindat Discovery Year",
    "Mindat Approval Year",
    "Mindat Publication Year",
    "Mindat IMA History",
    "Mindat IMA Symbol",
    "Mindat Strunz 10 Class",
    "Mindat Strunz 10 Subclass",
    "Mindat Strunz 10 Division",
    "Mindat Strunz 10 Group",
    "Mindat Dana 8 Class",
    "Mindat Dana 8 Type",
    "Mindat Dana 8 Group",
    "Mindat Dana 8 Number",
    "Mindat Colour",
    "Mindat Streak",
    "Mindat Lustre",
    "Mindat Lustre Type",
    "Mindat Diapheny",
    "Mindat Hardness Minimum",
    "Mindat Hardness Maximum",
    "Mindat Hardness Type",
    "Mindat Measured Density",
    "Mindat Calculated Density",
    "Mindat Crystal System",
    "Mindat Crystal Class",
    "Mindat Space Group",
    "Mindat Unit Cell a",
    "Mindat Unit Cell b",
    "Mindat Unit Cell c",
    "Mindat Unit Cell Alpha",
    "Mindat Unit Cell Beta",
    "Mindat Unit Cell Gamma",
    "Mindat Unit Cell Volume",
    "Mindat Cleavage",
    "Mindat Cleavage Type",
    "Mindat Fracture Type",
    "Mindat Tenacity",
    "Mindat Magnetism",
    "Mindat Optical Type",
    "Mindat Optical Sign",
    "Mindat Optical Colour",
    "Mindat Optical Birefringence",
    "Mindat Optical 2V Calculated",
    "Mindat Optical 2V Measured",
    "Mindat Weighting",
]

FIELD_MAP = {
    "Mindat ID": "id",
    "Mindat Long ID": "longid",
    "Mindat GUID": "guid",
    "Mindat Updated": "updttime",
    "Mindat Entry Type": "entrytype",
    "Mindat Entry Type Text": "entrytype_text",
    "Mindat Formula": "mindat_formula",
    "Mindat Formula Note": "mindat_formula_note",
    "Mindat IMA Formula": "ima_formula",
    "Mindat IMA Status": "ima_status",
    "Mindat IMA Notes": "ima_notes",
    "Mindat Description": "description_short",
    "Mindat Elements": "elements",
    "Mindat Significant Elements": "sigelements",
    "Mindat Key Elements": "key_elements",
    "Mindat Discovery Year": "discovery_year",
    "Mindat Approval Year": "approval_year",
    "Mindat Publication Year": "publication_year",
    "Mindat IMA History": "ima_history",
    "Mindat IMA Symbol": "shortcode_ima",
    "Mindat Strunz 10 Class": "strunz10ed1",
    "Mindat Strunz 10 Subclass": "strunz10ed2",
    "Mindat Strunz 10 Division": "strunz10ed3",
    "Mindat Strunz 10 Group": "strunz10ed4",
    "Mindat Dana 8 Class": "dana8ed1",
    "Mindat Dana 8 Type": "dana8ed2",
    "Mindat Dana 8 Group": "dana8ed3",
    "Mindat Dana 8 Number": "dana8ed4",
    "Mindat Colour": "colour",
    "Mindat Streak": "streak",
    "Mindat Lustre": "lustre",
    "Mindat Lustre Type": "lustretype",
    "Mindat Diapheny": "diapheny",
    "Mindat Hardness Minimum": "hmin",
    "Mindat Hardness Maximum": "hmax",
    "Mindat Hardness Type": "hardtype",
    "Mindat Measured Density": "dmeas",
    "Mindat Calculated Density": "dcalc",
    "Mindat Crystal System": "csystem",
    "Mindat Crystal Class": "cclass",
    "Mindat Space Group": "spacegroup",
    "Mindat Unit Cell a": "a",
    "Mindat Unit Cell b": "b",
    "Mindat Unit Cell c": "c",
    "Mindat Unit Cell Alpha": "alpha",
    "Mindat Unit Cell Beta": "beta",
    "Mindat Unit Cell Gamma": "gamma",
    "Mindat Unit Cell Volume": "va3",
    "Mindat Cleavage": "cleavage",
    "Mindat Cleavage Type": "cleavagetype",
    "Mindat Fracture Type": "fracturetype",
    "Mindat Tenacity": "tenacity",
    "Mindat Magnetism": "magnetism",
    "Mindat Optical Type": "opticaltype",
    "Mindat Optical Sign": "opticalsign",
    "Mindat Optical Colour": "opticalcolour",
    "Mindat Optical Birefringence": "opticalbirefringence",
    "Mindat Optical 2V Calculated": "optical2vcalc",
    "Mindat Optical 2V Measured": "optical2vmeasured",
    "Mindat Weighting": "weighting",
}

# The source table calls native elements by their bare element names. Mindat
# records the same species under its explicit ``Native <element>`` convention.
# Keep aliases explicit rather than applying this rule generally, so unrelated
# mineral names are never silently guessed. Cerium has no matching IMA record
# in the downloaded Mindat response and is deliberately left unmatched.
SOURCE_TO_MINDAT_ALIASES = {
    "Aluminium": "Native Aluminium",
    "Antimony": "Native Antimony",
    "Arsenic": "Native Arsenic",
    "Bismuth": "Native Bismuth",
    "Cadmium": "Native Cadmium",
    "Chromium": "Native Chromium",
    "Copper": "Native Copper",
    "Gold": "Native Gold",
    "Indium": "Native Indium",
    "Iridium": "Native Iridium",
    "Iron": "Native Iron",
    "Lead": "Native Lead",
    "Mercury": "Native Mercury",
    "Nickel": "Native Nickel",
    "Osmium": "Native Osmium",
    "Palladium": "Native Palladium",
    "Platinum": "Native Platinum",
    "Rhodium": "Native Rhodium",
    "Ruthenium": "Native Ruthenium",
    "Selenium": "Native Selenium",
    "Silicon": "Native Silicon",
    "Silver": "Native Silver",
    "Sulphur": "Native Sulphur",
    "Tellurium": "Native Tellurium",
    "Tin": "Native Tin",
    "Titanium": "Native Titanium",
    "Tungsten": "Native Tungsten",
    "Vanadium": "Native Vanadium",
    "Zinc": "Native Zinc",
}

# Cerium is a source-table IMA species but is not present in the current
# ``v1/minerals-ima`` listing. Mindat's individual geomaterial page/API record
# exists as Native Cerium (ID 46643), with IMA status QUESTIONABLE. This is the
# deliberately audited exception to the downloaded-list-only merge.
MANUAL_MINDAT_ID_OVERRIDES = {"Cerium": CERIUM_MINDAT_ID}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--batch-directory", type=Path, default=DEFAULT_BATCH_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def normalized_name(name: str) -> str:
    """Normalize known presentation-only differences without guessing aliases."""
    decomposed = unicodedata.normalize("NFKD", name).casefold()
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", unaccented)


def read_mindat_records(batch_directory: Path) -> Iterable[dict[str, Any]]:
    paths = sorted(batch_directory.glob("geomaterials_*.json"))
    if not paths:
        raise FileNotFoundError(f"No Mindat batches found in {batch_directory}")
    for path in paths:
        with path.open(encoding="utf-8") as source:
            response = json.load(source)
        yield from response.get("results", [])


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries for the one audited API override."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def fetch_mindat_record(record_id: int) -> dict[str, Any]:
    """Fetch one known Mindat geomaterial record using the existing API key."""
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("MINDAT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINDAT_API_KEY is required to fetch the Cerium override")
    request = Request(
        f"{MINDAT_API_ROOT}/v1/geomaterials/{record_id}/?format=json",
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            record = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to fetch Mindat record {record_id}") from error
    if not isinstance(record, dict) or record.get("id") != record_id:
        raise RuntimeError(f"Mindat returned an unexpected record for ID {record_id}")
    return record


def csv_value(value: Any) -> str | int | float:
    """Store scalar values directly and serialize list fields consistently."""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if value is None:
        return ""
    return value


def main() -> None:
    args = parse_args()
    with args.source.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "Mineral Name" not in reader.fieldnames:
            raise RuntimeError(f"{args.source} must contain a 'Mineral Name' column")
        source_columns = reader.fieldnames
        source_rows = list(reader)

    records_by_name: dict[str, dict[str, Any]] = {}
    duplicate_mindat_keys: list[str] = []
    for record in read_mindat_records(args.batch_directory):
        name_key = normalized_name(str(record.get("name", "")))
        if not name_key:
            continue
        if name_key in records_by_name:
            duplicate_mindat_keys.append(str(record.get("name", "")))
        else:
            records_by_name[name_key] = record
    if duplicate_mindat_keys:
        raise RuntimeError(f"Ambiguous normalized Mindat names: {duplicate_mindat_keys[:10]}")

    matched_rows: list[dict[str, Any]] = []
    unmatched_names: list[str] = []
    used_mindat_names: set[str] = set()
    for row in source_rows:
        source_name = row["Mineral Name"]
        override_id = MANUAL_MINDAT_ID_OVERRIDES.get(source_name)
        record = fetch_mindat_record(override_id) if override_id else None
        mindat_name = SOURCE_TO_MINDAT_ALIASES.get(source_name, source_name)
        record = record or records_by_name.get(normalized_name(mindat_name))
        if record is None:
            unmatched_names.append(source_name)
            continue

        output_row = dict(row)
        for column in MINDAT_COLUMNS:
            output_row[column] = csv_value(record.get(FIELD_MAP[column], ""))
        matched_rows.append(output_row)
        used_mindat_names.add(str(record["name"]))

    output_columns = [*source_columns, *MINDAT_COLUMNS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=output_columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(matched_rows)

    unmatched_mindat_names = sorted(
        str(record["name"])
        for record in records_by_name.values()
        if str(record["name"]) not in used_mindat_names
    )
    report = {
        "source_file": str(args.source.resolve()),
        "mindat_batch_directory": str(args.batch_directory.resolve()),
        "output_file": str(args.output.resolve()),
        "source_rows": len(source_rows),
        "mindat_records": len(records_by_name),
        "matched_rows": len(matched_rows),
        "dropped_source_rows": len(unmatched_names),
        "unmatched_source_names": sorted(unmatched_names),
        "unmatched_mindat_records": len(unmatched_mindat_names),
        "unmatched_mindat_names": unmatched_mindat_names,
        "matching": "case-insensitive; Unicode accents, punctuation, and spacing ignored",
        "explicit_source_to_mindat_aliases": SOURCE_TO_MINDAT_ALIASES,
        "manual_mindat_id_overrides": MANUAL_MINDAT_ID_OVERRIDES,
        "added_mindat_columns": MINDAT_COLUMNS,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(matched_rows)} matched minerals to {args.output}")
    print(f"Dropped {len(unmatched_names)} source rows; details: {args.report}")


if __name__ == "__main__":
    main()
