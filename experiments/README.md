# Experiments

Exploratory work kept as documentation of the project's iteration. **Nothing in this folder is part of the production pipeline**, the shipped data in `mineral-map/public/data/` comes from `analysis.ipynb` at the repository root.

## `optimize_component_weights.ipynb`

A reproducible study that searched for better additive component weights than the hand-picked baseline `[0.43, 0.33, 0.12, 0.05, 0.05, 0.02]`. It evaluated 512 Dirichlet candidate weight vectors against graph stability, effective-component entropy, redundancy, and Strunz-class continuity, then exported one deterministic winner (candidate #274: ≈ 0.310 / 0.322 / 0.158 / 0.091 / 0.080 / 0.039). The full evaluation is in `component_weight_optimization_report.json`.

The notebook also regenerated the neighbour graph from **256-landmark approximate** distance caches instead of the exact all-pairs matrix. That approximate topology was judged worse than the exact graph and reverted, the live app uses the exact 10-NN graph with the optimized weights. The legacy 256-landmark caches have been deleted; re-running the approximate section of this notebook would require regenerating them first.

> **Note:** the notebook is saved mid-experiment (one cell was removed after execution), so the approximate-regeneration cells reference names that are no longer defined and need to be re-run in order to work. The weight-optimization section is self-contained.

## `reapply_neighbor_taxonomy.py`

A one-time repair script written after an exploratory export replaced every edge's relationship category with the generic `exact_additive_knn` label. It recovers the original taxonomy labels (polymorph, hydration variant, …) with a linear scan of `mineral_visualization_edges.csv` and rewrites them into the neighbour JSON. Idempotent and safe to re-run, but only needed if the categories in `mineral-map/public/data/mineral-map-neighbors.json` are ever clobbered again.
