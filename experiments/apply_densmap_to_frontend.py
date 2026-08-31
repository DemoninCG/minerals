"""Update the frontend data files to use densMAP coordinates.

Overwrites the coordinate fields in mineral-map/public/data/mineral-map-nodes.json
with normalized densMAP coordinates (per-axis center + scale to ~[-0.95, 0.95]),
matching the normalization convention the previous force-directed export used and
the ~[-0.95, 0.95] range the app's metadata documents. Node metadata, the
neighbor JSON, and the classification-sync output are untouched: the sync script
only patches classification fields and preserves coordinates.

Coordinates come from experiments/results/densmap_coords.npy (written by
experiments/compare_global_embeddings.py, densMAP with metric="precomputed",
n_neighbors=30, min_dist=0.12, random_state=42 on additive_exact_distances_v3.npy).
Run compare_global_embeddings.py first if that file does not exist.
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
NODES_PATH = ROOT / "mineral-map" / "public" / "data" / "mineral-map-nodes.json"
METADATA_PATH = ROOT / "mineral-map" / "public" / "data" / "mineral-map-metadata.json"
COORDS_PATH = ROOT / "experiments" / "results" / "densmap_coords.npy"

COORDINATE_SYSTEM = (
    "normalized 3D densMAP embedding of the exact additive distance matrix; "
    "edge distances and component values remain authoritative"
)
MAP_PARAMETERS = {
    "algorithm": "densMAP (UMAP with density-preserving objective)",
    "metric": "precomputed exact additive distance",
    "dimensions": 3,
    "nNeighbors": 30,
    "minDist": 0.12,
    "randomState": 42,
    "normalization": "per-axis center and scale to approximately [-0.95, 0.95]",
}


def main() -> None:
    if not COORDS_PATH.exists():
        raise SystemExit(
            f"{COORDS_PATH} not found. Run experiments/compare_global_embeddings.py first."
        )

    raw_coords = np.load(COORDS_PATH).astype(np.float64)
    with NODES_PATH.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    nodes = payload["nodes"]
    if len(raw_coords) != len(nodes):
        raise SystemExit(f"Coordinate count {len(raw_coords)} != node count {len(nodes)}.")

    # Per-axis normalization to ~[-0.95, 0.95], centered at the origin: the same
    # convention as the force-directed export, so SCENE_SCALE rendering is unchanged.
    centered = raw_coords - raw_coords.mean(axis=0, keepdims=True)
    scaled = centered / (np.ptp(centered, axis=0, keepdims=True) / 2).max() * 0.95
    scaled -= scaled.mean(axis=0, keepdims=True)

    for node, (x, y, z) in zip(nodes, scaled):
        node["coordinates"] = [float(x), float(y), float(z)]

    payload["coordinateSystem"] = COORDINATE_SYSTEM

    with METADATA_PATH.open(encoding="utf-8") as fh:
        metadata = json.load(fh)
    distance_model = metadata.setdefault("distanceModel", {})
    distance_model["coordinateCaveat"] = (
        "densMAP coordinates are normalized embedding positions; edge distances "
        "and component values remain authoritative."
    )
    distance_model["mapAlgorithm"] = "densMAP 3D embedding of the exact additive distance matrix"
    distance_model["mapParameters"] = MAP_PARAMETERS
    metadata["coordinateSystem"] = COORDINATE_SYSTEM

    nodes_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    metadata_text = json.dumps(metadata, ensure_ascii=True, indent=2) + "\n"
    NODES_PATH.write_text(nodes_text, encoding="utf-8")
    METADATA_PATH.write_text(metadata_text, encoding="utf-8")

    extents = np.ptp(scaled, axis=0)
    print(f"Updated coordinates for {len(nodes):,} nodes in {NODES_PATH.name}.")
    print(f"Per-axis extents after normalization: {np.round(extents, 3).tolist()}")
    print(f"Updated metadata mapAlgorithm to: {distance_model['mapAlgorithm']}")


if __name__ == "__main__":
    main()
