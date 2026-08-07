"""Reapply the original relationship taxonomy to the exported 10-NN neighbours.

The approximate/topology export replaced every edge category with the generic
"exact_additive_knn" label, so the frontend stopped showing the taxonomy classes
(cation_analogue, polymorph, ...). This script patches ONLY the k-NN edges that
the frontend displays:

- Relationship names are not recalculated. They are recovered with a single
  linear scan of mineral_visualization_edges.csv, which stores
  relationship_category for each original directed edge (~1.4 s).
- Edges in the neighbour payload that cannot be matched to the CSV (possible
  only for approximate regeneration output) fall back to a clearly-marked
  "approximate_landmark_neighbour" category.
- Metadata keeps the authoritative relationshipCategories map, adding the
  fallback description if it is absent.

Runtime is a few seconds, dominated by rewriting the two ~25 MB neighbour JSONs.
"""

import csv
import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EDGE_CSV = ROOT / "mineral_visualization_edges.csv"
NEIGHBOR_PATHS = (
    ROOT / "web_export" / "mineral-map-neighbors.json",
    ROOT / "mineral-map" / "public" / "data" / "mineral-map-neighbors.json",
)
METADATA_PATHS = (
    ROOT / "web_export" / "mineral-map-metadata.json",
    ROOT / "mineral-map" / "public" / "data" / "mineral-map-metadata.json",
)
FALLBACK_CATEGORY = "approximate_landmark_neighbour"
FALLBACK_DESCRIPTION = (
    "Nearest neighbour found by an exploratory landmark-signature search; "
    "relationship class is pending exact pairwise recomputation."
)


def main() -> None:
    start = time.time()
    with METADATA_PATHS[0].open(encoding="utf-8") as input_file:
        metadata_payload = json.load(input_file)
    taxonomy = dict(metadata_payload.get("relationshipCategories", {}))
    taxonomy.setdefault(FALLBACK_CATEGORY, FALLBACK_DESCRIPTION)

    old_category_by_pair: dict[tuple[int, int], str] = {}
    with EDGE_CSV.open(newline="", encoding="utf-8-sig") as input_file:
        for row in csv.DictReader(input_file):
            category = row.get("relationship_category", "")
            if category:
                old_category_by_pair[(int(row["source_index"]), int(row["target_index"]))] = category

    category_counts: Counter[str] = Counter()
    for neighbor_path in NEIGHBOR_PATHS:
        with neighbor_path.open(encoding="utf-8") as input_file:
            neighbor_payload = json.load(input_file)
        unmatched = 0
        for source_id, source_neighbors in enumerate(neighbor_payload["neighborsBySourceId"]):
            for entry in source_neighbors:
                category = old_category_by_pair.get((source_id, int(entry["targetId"])), FALLBACK_CATEGORY)
                entry["category"] = category
                category_counts[category] += 1
                if category == FALLBACK_CATEGORY:
                    unmatched += 1
        neighbor_path.write_text(
            json.dumps(neighbor_payload, ensure_ascii=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print(f"{neighbor_path.name}: {len(neighbor_payload['neighborsBySourceId']):,} sources patched, {unmatched:,} unmatched.")

    for metadata_path in METADATA_PATHS:
        with metadata_path.open(encoding="utf-8") as input_file:
            meta = json.load(input_file)
        meta["relationshipCategories"] = taxonomy
        metadata_path.write_text(
            json.dumps(meta, ensure_ascii=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    print(f"\nRelabelled {sum(category_counts.values()):,} directed k-NN edges:")
    for category, count in category_counts.most_common():
        print(f"  {category}: {count:,}")
    print(f"Finished in {time.time() - start:.1f}s.")


if __name__ == "__main__":
    main()
