"""Compare densMAP, PaCMAP, and TriMap on the exact additive distance matrix.

Each method consumes the precomputed 6228x6228 additive dissimilarity through its
supported custom-distance path:

- densMAP (UMAP): metric="precomputed" (native support).
- PaCMAP: no precomputed metric, but pair selection is fully injectable. We
  reproduce library pair construction (NN ranked by d^2/(sigma_i sigma_j), MN by
  a distance-aware 6-candidate draw, FP by rejection sampling of non-neighbors)
  using the additive matrix, then hand all three pair arrays to fit_transform,
  which takes the "Using stored pairs" branch and never touches X for distances.
- TriMap: use_dist_matrix=True (X is interpreted as the pairwise distance matrix).

Outputs: coordinates under experiments/results/, metrics to stdout, and a
3-panel x 2-view 3D comparison figure under docs/.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import umap
from scipy.stats import spearmanr
from sklearn.manifold import trustworthiness
from sklearn.metrics import pairwise_distances

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
RANDOM_STATE = 42

# ---------------------------------------------------------------- load data
D = np.load(ROOT / "additive_exact_distances_v3.npy").astype(np.float64)
n = len(D)
D32 = D.astype(np.float32)

with (ROOT / "IMA_data_with_derived_strunz.csv").open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))
strunz = np.array([row["Derived Strunz Top-Level"] for row in rows])
assert len(strunz) == n

iu = np.triu_indices(n, k=1)
rng = np.random.default_rng(0)
sample = rng.choice(len(iu[0]), size=300_000, replace=False)
pair_d = D[iu[0][sample], iu[1][sample]]
p10, p90 = np.percentile(pair_d, [10, 90])

# ------------------------------------------------------------- metric suite
def evaluate(name: str, coords: np.ndarray) -> dict[str, float]:
    coords = np.asarray(coords, dtype=np.float64)
    emb = pairwise_distances(coords)

    r = rng.integers(0, n, size=4000)
    emb_rows = np.argpartition(emb[r], 11, axis=1)[:, :11]
    true_rows = np.argpartition(D32[r], 11, axis=1)[:, :11]
    knn10 = float(np.mean([
        len({x for x in er if x != ri} & {x for x in tr if x != ri}) / 10
        for ri, er, tr in zip(r, emb_rows, true_rows)
    ]))
    purity = float(np.mean([np.mean(strunz[er] == strunz[ri]) for ri, er in zip(r, emb_rows)]))

    emb_pair = emb[iu[0][sample], iu[1][sample]]
    near_mask, far_mask = pair_d <= p10, pair_d >= p90
    rho_near = float(spearmanr(pair_d[near_mask], emb_pair[near_mask]).statistic)
    rho_far = float(spearmanr(pair_d[far_mask], emb_pair[far_mask]).statistic)

    tw = float(trustworthiness(D, coords, n_neighbors=10, metric="precomputed"))

    unit = (coords - coords.min(axis=0)) / np.ptp(coords, axis=0)
    g16 = np.minimum((unit * 16).astype(int), 15)
    occ16 = int(len(np.unique(g16, axis=0)))
    counts = np.sort(np.bincount(g16[:, 0] * 256 + g16[:, 1] * 16 + g16[:, 2], minlength=4096))
    counts = counts[counts > 0]
    cum = np.cumsum(counts)
    gini = float(1.0 - 2.0 * np.sum(cum / cum[-1]) / len(counts) + 1.0 / len(counts))

    metrics = {
        "knn10": knn10, "trust10": tw, "rho_near": rho_near, "rho_far": rho_far,
        "occ16": occ16, "gini16": gini, "strunz_purity": purity,
    }
    print(
        f"{name}: knn@10={knn10:.3f} trust@10={tw:.3f} rho_near={rho_near:.3f} rho_far={rho_far:.3f} "
        f"occ16={occ16}/4096 gini16={gini:.3f} strunzNNpurity={purity:.3f}"
    )
    np.save(RESULTS_DIR / f"{name}_coords.npy", coords.astype(np.float32))
    return metrics


# ----------------------------------------------------------------- densMAP
def run_densmap(n_neighbors: int = 30) -> np.ndarray:
    t0 = time.time()
    reducer = umap.UMAP(
        metric="precomputed", n_components=3, n_neighbors=n_neighbors, min_dist=0.12,
        densmap=True, random_state=RANDOM_STATE,
    )
    coords = reducer.fit_transform(D)
    print(f"[densmap] fit in {time.time() - t0:.0f}s")
    return coords


# ------------------------------------------------------------------ pacmap
def pacmap_pairs_from_distances(dist: np.ndarray, n_neighbors: int, n_mn: int, n_fp: int, random_state: int):
    """Rebuild PaCMAP's three pair sets from a precomputed dissimilarity matrix.

    Mirrors pacmap.generate_pair for a custom metric: the candidate neighbor
    pool is the 50+n_neighbors nearest rows; sigma_i is the mean 4th-6th
    smallest distance; neighbor pairs keep the n_neighbors candidates with the
    smallest scaled distance d^2/(sigma_i sigma_j); MN pairs keep the
    second-closest of 6 distance-ordered random draws; FP pairs are
    rejection-sampled non-neighbors (library helper; X is unused there).
    """
    from pacmap.pacmap import sample_FP_pair_deterministic

    n = dist.shape[0]
    extra = min(n_neighbors + 50, n - 1)
    knn_idx = np.argsort(dist, axis=1)[:, 1 : extra + 1]
    d_knn = np.take_along_axis(dist, knn_idx, axis=1)
    sig = np.maximum(d_knn[:, 3:6].mean(axis=1), 1e-10)
    scaled = d_knn**2 / (sig[:, None] * sig[knn_idx])
    chosen = np.take_along_axis(knn_idx, np.argsort(scaled, axis=1)[:, :n_neighbors], axis=1)
    pair_neighbors = np.empty((n * n_neighbors, 2), dtype=np.int32)
    pair_neighbors[:, 0] = np.repeat(np.arange(n), n_neighbors)
    pair_neighbors[:, 1] = chosen.reshape(-1)

    # MN: 6 random candidates, drop the closest, keep the next closest (as in
    # sample_MN_pair_deterministic but with precomputed distances).
    pair_MN = np.empty((n * n_mn, 2), dtype=np.int32)
    for i in range(n):
        for j in range(n_mn):
            np.random.seed(random_state + i * n_mn + j)
            candidates: list[int] = []
            while len(candidates) < 6:
                cand = int(np.random.randint(n))
                if cand != i and cand not in candidates:
                    candidates.append(cand)
            draw = dist[i, candidates]
            drop = int(np.argmin(draw))
            keep = [c for k, c in enumerate(candidates) if k != drop]
            pair_MN[i * n_mn + j] = (i, keep[int(np.argmin(np.delete(draw, drop)))])

    # FP: rejection-sample non-neighbors (library helper needs X only for shapes).
    pair_FP = sample_FP_pair_deterministic(
        np.zeros((n, 1), dtype=np.float32), pair_neighbors, n_neighbors, n_fp, random_state
    )
    return pair_neighbors, pair_MN, pair_FP


def run_pacmap(n_neighbors: int = 30) -> np.ndarray:
    import pacmap

    n_mn, n_fp = int(0.5 * n_neighbors), int(2.0 * n_neighbors)
    pair_neighbors, pair_MN, pair_FP = pacmap_pairs_from_distances(
        D32, n_neighbors, n_mn, n_fp, RANDOM_STATE
    )
    model = pacmap.PaCMAP(
        n_components=3, n_neighbors=n_neighbors, MN_ratio=0.5, FP_ratio=2.0,
        apply_pca=False, random_state=RANDOM_STATE,
    )
    model.pair_neighbors = pair_neighbors
    model.pair_MN = pair_MN
    model.pair_FP = pair_FP
    # X is unused for the loss (pairs fully specify the graph); supply a benign
    # 4-feature dummy so preprocess_X's min-max + PCA(3) init path stays finite.
    dummy = np.linspace(0.0, 1.0, n, dtype=np.float32).reshape(n, 1) @ np.ones((1, 4), dtype=np.float32)
    t0 = time.time()
    coords = model.fit_transform(dummy, init="random", save_pairs=False)
    print(f"[pacmap nn={n_neighbors}] fit in {time.time() - t0:.0f}s")
    return coords


# ------------------------------------------------------------------- trimap
def run_trimap(n_inliers: int = 12, n_outliers: int = 4, n_random: int = 3) -> np.ndarray:
    import trimap

    model = trimap.TRIMAP(
        n_dims=3, n_inliers=n_inliers, n_outliers=n_outliers, n_random=n_random,
        use_dist_matrix=True, apply_pca=False, verbose=False,
    )
    # TriMap seeds all randomness from the global numpy RNG.
    np.random.seed(RANDOM_STATE)
    t0 = time.time()
    coords = model.fit_transform(D32.copy())
    print(f"[trimap i={n_inliers} o={n_outliers} r={n_random}] fit in {time.time() - t0:.0f}s")
    return coords


# --------------------------------------------------------------------- main
def main() -> None:
    configs = [
        ("densmap", "nn30", run_densmap, {}),
        ("pacmap", "nn30", run_pacmap, {"n_neighbors": 30}),
        ("pacmap", "nn10", run_pacmap, {"n_neighbors": 10}),
        ("trimap", "i12o4r3", run_trimap, {}),
        ("trimap", "i12o2r1", run_trimap, {"n_outliers": 2, "n_random": 1}),
    ]
    runs: list[tuple[str, str, dict[str, float], np.ndarray]] = []
    for method, tag, runner, kwargs in configs:
        coords = runner(**kwargs)
        metrics = evaluate(f"{method}[{tag}]", coords)
        runs.append((method, tag, metrics, coords))

    print("\n=== all runs ===")
    print("method            knn@10 trust10 rho_near rho_far occ16  gini16 purity")
    for method, tag, m, _ in runs:
        print(
            f"{method+'['+tag+']':<17} {m['knn10']:.3f}  {m['trust10']:.3f} {m['rho_near']:+.3f}   "
            f"{m['rho_far']:+.3f}  {m['occ16']:>4d}  {m['gini16']:.3f}  {m['strunz_purity']:.3f}"
        )

    # Per-method winner: most spatially spread among faithful embeddings.
    best: dict[str, tuple[str, dict[str, float], np.ndarray]] = {}
    for method, tag, m, coords in runs:
        eligible = m["trust10"] >= 0.985 and m["strunz_purity"] >= 0.82
        if method not in best:
            best[method] = (tag, m, coords)
        else:
            current = best[method][1]
            if eligible and (not (current["trust10"] >= 0.985 and current["strunz_purity"] >= 0.82) or m["occ16"] > current["occ16"]):
                best[method] = (tag, m, coords)

    print("\n=== selected per method ===")
    for method, (tag, m, _) in best.items():
        print(f"{method}: {tag} (occ16={m['occ16']}, trust10={m['trust10']:.3f})")

    for method, (tag, m, coords) in best.items():
        np.save(RESULTS_DIR / f"{method}_coords.npy", coords.astype(np.float32))

    plot_comparison({method: coords for method, (_, _, coords) in best.items()})


def plot_comparison(selected: dict[str, np.ndarray]) -> None:
    titles = {
        "densmap": "densMAP (UMAP densmap=True)",
        "pacmap": "PaCMAP (injected additive-distance pairs)",
        "trimap": "TriMap (use_dist_matrix)",
    }
    cmap = plt.get_cmap("tab10")
    divisions = sorted(set(strunz))

    fig = plt.figure(figsize=(22, 14), layout="constrained")
    for col, name in enumerate(("densmap", "pacmap", "trimap")):
        coords = selected[name]
        for view, (elev, azim) in enumerate(((24, -58), (12, 55))):
            ax = fig.add_subplot(2, 3, view * 3 + col + 1, projection="3d")
            for di, division in enumerate(divisions):
                mask = strunz == division
                ax.scatter(
                    coords[mask, 0], coords[mask, 1], coords[mask, 2],
                    s=3, alpha=0.45, color=cmap(di), depthshade=False, rasterized=True,
                )
            ax.view_init(elev=elev, azim=azim)
            ax.set_title(f"{titles[name]} - view {view + 1}", fontsize=10)
            ax.set_box_aspect(np.ptp(coords, axis=0))
    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=6,
                   markerfacecolor=cmap(i), markeredgecolor="none", label=d)
        for i, d in enumerate(divisions)
    ]
    fig.legend(handles=handles, loc="outside right upper", title="Strunz division")
    out = ROOT / "docs" / "experiment-densmap-pacmap-trimap.png"
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
