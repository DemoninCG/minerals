"""Download Mindat records for the IMA mineral dataset.

The Mindat API is in active development, so this script deliberately calls the
documented HTTP endpoints directly rather than depending on a particular
OpenMindat release.  It is restartable: successful batches are retained and
only missing batches are requested on a later run.

The API data is currently intended for private, non-commercial use.  Review
Mindat's current API terms before redistributing the files this creates.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.mindat.org"
ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "mindat_export"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
BATCH_SIZE = 150

# A curated subset would make downstream tables smaller, but the Mindat
# ``fields=*`` response is already compact enough for 6,239 minerals and
# preserves useful fields we may discover later. This includes the requested
# Dana/Strunz codes, discovery and approval/publication years, colour,
# hardness, density, crystallography, optical properties, and chemistry.
GEOMATERIAL_FIELDS = "*"

# Mindat presently returns HTTP 500 for every tested ``expand`` request. Keep
# this blank until the API's expansion endpoints are repaired. In particular,
# do not request ``locality``: every occurrence for every mineral would be
# exceptionally large and is not needed for compositional classification.
GEOMATERIAL_EXPANSIONS = ""


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--output-dir",
		type=Path,
		default=DEFAULT_OUTPUT,
		help="Directory for raw API responses and the manifest.",
	)
	parser.add_argument(
		"--refresh",
		action="store_true",
		help="Download again even when a local response already exists.",
	)
	parser.add_argument(
		"--max-minerals",
		type=int,
		help="Limit the number of minerals; useful for a small API test.",
	)
	return parser.parse_args()


def load_dotenv(path: Path) -> None:
	"""Load simple KEY=VALUE entries without replacing real environment values."""
	if not path.is_file():
		return

	for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
		line = raw_line.strip()
		if not line or line.startswith("#"):
			continue
		if line.startswith("export "):
			line = line.removeprefix("export ").lstrip()
		if "=" not in line:
			print(f"Ignoring malformed .env entry on line {line_number}")
			continue

		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip()
		if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
			value = value[1:-1]
		if key:
			os.environ.setdefault(key, value)


def write_json(path: Path, value: Any) -> None:
	"""Atomically write JSON so an interrupted download never looks complete."""
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary_path = path.with_suffix(path.suffix + ".part")
	temporary_path.write_text(
		json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
	)
	temporary_path.replace(path)


def read_json(path: Path) -> Any:
	with path.open(encoding="utf-8") as source:
		return json.load(source)


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
	for start in range(0, len(values), size):
		yield values[start : start + size]


class MindatClient:
	"""Small authenticated client with retry handling and page aggregation."""

	def __init__(self, api_key: str) -> None:
		self.headers = {
			"Authorization": f"Token {api_key}",
			"Accept": "application/json",
			"User-Agent": "IMA-mineral-visualization-data-collector/1.0",
		}

	def get_all(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
		"""Retrieve all pages from an API list endpoint as one JSON object."""
		query = urlencode(params or {}, doseq=True)
		url = f"{API_ROOT}/{endpoint.strip('/')}"
		if query:
			url = f"{url}?{query}"

		first_page = self._get_json(url)
		if not isinstance(first_page, dict) or "results" not in first_page:
			# Detail endpoints and a few evolving endpoints return an object.
			return {"count": 1, "results": [first_page]}

		results = list(first_page["results"])
		next_url = first_page.get("next")
		while next_url:
			page = self._get_json(next_url)
			if not isinstance(page, dict) or "results" not in page:
				raise RuntimeError(f"Unexpected paginated response from {next_url!r}")
			results.extend(page["results"])
			next_url = page.get("next")

		first_page["results"] = results
		first_page["count"] = len(results)
		first_page["next"] = None
		return first_page

	def _get_json(self, url: str) -> Any:
		last_error: Exception | None = None
		for attempt in range(MAX_RETRIES):
			try:
				request = Request(url, headers=self.headers)
				with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
					return json.load(response)
			except HTTPError as error:
				# Authentication and most 4xx errors are not transient.
				if error.code not in {429, 500, 502, 503, 504}:
					body = error.read().decode("utf-8", errors="replace")[:500]
					raise RuntimeError(f"Mindat API returned HTTP {error.code}: {body}") from error
				last_error = error
			except (URLError, TimeoutError, json.JSONDecodeError) as error:
				last_error = error

			delay = min(30, 2**attempt)
			print(f"Request failed ({last_error}); retrying in {delay}s...")
			time.sleep(delay)
		raise RuntimeError(f"Mindat API did not respond after {MAX_RETRIES} attempts") from last_error


def fetch_once(
	client: MindatClient,
	endpoint: str,
	output_path: Path,
	*,
	params: dict[str, Any] | None = None,
	refresh: bool,
) -> dict[str, Any]:
	if output_path.exists() and not refresh:
		print(f"Keeping existing {output_path.name}")
		return read_json(output_path)
	print(f"Downloading {endpoint}...")
	response = client.get_all(endpoint, params)
	write_json(output_path, response)
	print(f"Saved {len(response.get('results', []))} records to {output_path.name}")
	return response


def ima_geomaterial_ids(ima_records: dict[str, Any]) -> list[int]:
	"""Return the official geomaterial IDs for the downloaded IMA records."""
	ids: set[int] = set()
	for mineral in ima_records.get("results", []):
		longid = str(mineral.get("mindat_longid", ""))
		parts = longid.split(":")
		if len(parts) >= 3 and parts[2].isdigit():
			ids.add(int(parts[2]))
	return sorted(ids)


def fetch_geomaterial_batches(
	client: MindatClient, output_dir: Path, ids: list[int], refresh: bool
) -> list[dict[str, Any]]:
	"""Fetch detailed records in URL-safe batches and retain every raw batch."""
	# Use a distinct directory from the earlier CSV-ID experiment. Its batches
	# may contain synonyms or non-IMA records and must not be mistaken for the
	# authoritative IMA-specific batches below.
	batch_directory = output_dir / "ima_geomaterial_batches"
	responses: list[dict[str, Any]] = []
	all_batches = list(chunks(ids, BATCH_SIZE))
	for index, batch in enumerate(all_batches, start=1):
		output_path = batch_directory / f"geomaterials_{index:03d}.json"
		print(f"Detailed mineral batch {index}/{len(all_batches)} ({len(batch)} IDs)")
		responses.append(
			fetch_once(
				client,
				"v1/geomaterials",
				output_path,
				params={
					"format": "json",
					"page-size": BATCH_SIZE,
					"id_in": ",".join(map(str, batch)),
					"fields": GEOMATERIAL_FIELDS,
				},
				refresh=refresh,
			)
		)
	return responses


def main() -> None:
	args = parse_args()
	# ``.env`` is a file, not an operating-system environment. Load the
	# conventional project-level file explicitly, while giving an already-set
	# environment variable precedence (useful for CI and production).
	load_dotenv(ROOT / ".env")
	api_key = os.environ.get("MINDAT_API_KEY", "").strip()
	if not api_key:
		raise SystemExit(
			"Set MINDAT_API_KEY in your environment before running this script. "
			"The key is intentionally not stored in source control."
		)

	client = MindatClient(api_key)
	output_dir = args.output_dir.resolve()
	output_dir.mkdir(parents=True, exist_ok=True)

	# The API currently returns HTTP 500 when its ``fields`` parameter is sent
	# to this endpoint, even for ``id,name``. Its default response works and
	# supplies the IMA-specific fields. The detailed geomaterial export below
	# supplies Dana, Strunz, physical, optical, crystallographic, and descriptive
	# fields.
	ima_records = fetch_once(
		client,
		"v1/minerals-ima",
		output_dir / "minerals_ima_all_fields.json",
		params={"format": "json", "page-size": 1500},
		refresh=args.refresh,
	)

	# Mindat's IMA listing is the authoritative set of 6,239 mineral species.
	# Its ``mindat_longid`` is structured as ``1:1:<geomaterial id>:...``;
	# query those IDs rather than the older, separately sourced CSV.
	ids = ima_geomaterial_ids(ima_records)
	if not ids:
		raise RuntimeError("No valid geomaterial IDs were found in the IMA response")
	if args.max_minerals is not None:
		if args.max_minerals <= 0:
			raise SystemExit("--max-minerals must be positive")
		ids = ids[: args.max_minerals]
	geomaterial_batches = fetch_geomaterial_batches(client, output_dir, ids, args.refresh)

	# The classification dictionaries make numeric Dana/Strunz codes in the
	# detailed mineral records understandable even if Mindat changes labels.
	classification_files = {
		"nickel_strunz_families.json": "v1/nickel-strunz-10/families",
		"nickel_strunz_classes.json": "v1/nickel-strunz-10/classes",
		"nickel_strunz_subclasses.json": "v1/nickel-strunz-10/subclasses",
		"dana8_groups.json": "v1/dana-8/groups",
		"dana8_subgroups.json": "v1/dana-8/subgroups",
	}
	for filename, endpoint in classification_files.items():
		fetch_once(
			client,
			endpoint,
			output_dir / "classifications" / filename,
			params={"format": "json", "page-size": 1500},
			refresh=args.refresh,
		)

	detailed_count = sum(len(batch.get("results", [])) for batch in geomaterial_batches)
	manifest = {
		"generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
		"source": API_ROOT,
		"notes": [
			"Raw API responses are retained without transforming or redistributing them.",
			"Locality-occurrence expansion is excluded because it is exceptionally large.",
			"Rerun without --refresh to resume missing batch files; use --refresh to replace them.",
		],
		"ima_endpoint_records": len(ima_records.get("results", [])),
		"requested_geomaterial_ids": len(ids),
		"downloaded_geomaterial_records": detailed_count,
		"geomaterial_batch_size": BATCH_SIZE,
		"geomaterial_fields": GEOMATERIAL_FIELDS,
		"geomaterial_expansions": (
			GEOMATERIAL_EXPANSIONS.split(",") if GEOMATERIAL_EXPANSIONS else []
		),
	}
	write_json(output_dir / "manifest.json", manifest)
	print("Download complete.")
	print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
	main()