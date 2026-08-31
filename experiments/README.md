# Experiments

Exploratory work kept as documentation of the project's iteration. **Nothing in this folder is part of the production pipeline**, the shipped data in `mineral-map/public/data/` comes from `analysis.ipynb` at the repository root.

## `compare_global_embeddings.py`

Compares three global-structure-preserving embeddings of the exact additive distance matrix (`additive_exact_distances_v3.npy`, 6,228²) as candidates to replace the shipped force-directed layout coordinates:

- **densMAP** — UMAP with `densmap=True` (`metric="precomputed"`, native precomputed-distance support).
- **PaCMAP** — has no precomputed-metric mode, so the script rebuilds the library's exact pair-construction procedure (NN pairs ranked by `d²/(σᵢσⱼ)`, MN pairs as second-closest of 6 random draws, FP pairs by rejection sampling) from the precomputed matrix and injects all three pair arrays; PaCMAP's loss uses only embedded distances, so this is faithful.
- **TriMap** — `use_dist_matrix=True` (native; seeds from the global numpy RNG).

Each run is scored on 10-NN preservation, trustworthiness, near/far Spearman correlation, 16³-grid occupancy (spatial spread), Gini concentration, and Strunz nearest-neighbour purity. Winner coordinates are saved under `results/`, and `docs/experiment-densmap-pacmap-trimap.png` shows the per-method winners from two angles.

Run with `.venv\Scripts\python.exe experiments\compare_global_embeddings.py` (needs `pacmap` and `trimap` pip packages; ~90 s total).

**Result (2026-08-31):** densMAP dominates on spatial spread (306/4096 occupied cells vs 178–240; Gini 0.73 vs 0.46–0.55) with the best local distance correlation (ρ_near 0.64) and no loss of Strunz purity. TriMap collapses toward a plane with axis-strung outliers; PaCMAP is competitive on local fidelity (nn=10) but concentrates into small islands. densMAP is the recommended replacement; `experiments/results/*.npy` hold the winning coordinates.

## `apply_densmap_to_frontend.py`

One-shot updater that writes the densMAP winner coordinates into `mineral-map/public/data/`: per-axis normalization to ~[-0.95, 0.95] (the same convention as the previous force-directed export, so the app's `SCENE_SCALE` rendering is unchanged), plus matching `coordinateSystem` / `mapAlgorithm` / `mapParameters` text in the metadata. Classification fields, the neighbour JSON, and per-node metadata are untouched, and the Mindat sync script preserves coordinates, so the update composes cleanly with `npm run sync:data`. Requires `compare_global_embeddings.py` to have run first.

## `optimize_component_weights.ipynb`

A reproducible study that searched for better additive component weights than the hand-picked baseline `[0.43, 0.33, 0.12, 0.05, 0.05, 0.02]`. It evaluated 512 Dirichlet candidate weight vectors against graph stability, effective-component entropy, redundancy, and Strunz-class continuity, then exported one deterministic winner (candidate #274: ≈ 0.310 / 0.322 / 0.158 / 0.091 / 0.080 / 0.039). The full evaluation is in `component_weight_optimization_report.json`.

The notebook also regenerated the neighbour graph from **256-landmark approximate** distance caches instead of the exact all-pairs matrix. That approximate topology was judged worse than the exact graph and reverted, the live app uses the exact 10-NN graph with the optimized weights. The legacy 256-landmark caches have been deleted; re-running the approximate section of this notebook would require regenerating them first.

> **Note:** the notebook is saved mid-experiment (one cell was removed after execution), so the approximate-regeneration cells reference names that are no longer defined and need to be re-run in order to work. The weight-optimization section is self-contained.

## `reapply_neighbor_taxonomy.py`

A one-time repair script written after an exploratory export replaced every edge's relationship category with the generic `exact_additive_knn` label. It recovers the original taxonomy labels (polymorph, hydration variant, …) with a linear scan of `mineral_visualization_edges.csv` and rewrites them into the neighbour JSON. Idempotent and safe to re-run, but only needed if the categories in `mineral-map/public/data/mineral-map-neighbors.json` are ever clobbered again.
