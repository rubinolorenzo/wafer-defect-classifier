"""Physically motivated features and a gradient-boosting baseline.

Before trusting a CNN, a process engineer would ask: how far do simple,
interpretable descriptors get you? Each feature below answers a question a
yield engineer would ask while looking at a wafer map:

* How many dies fail, and where along the radius?        -> radial profile
* Are the edge failures all on one side?                  -> sector asymmetry
* Is there one compact blob, or a thin line?              -> largest cluster shape
* Is the failure spread out or concentrated?              -> cluster count, spread

All features are invariant to wafer rotation, like the defect classes.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

N_RADIAL = 8
N_SECTORS = 8


def _polar(size: int):
    c = (size - 1) / 2
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.hypot(yy - c, xx - c) / (size / 2)
    theta = np.arctan2(yy - c, xx - c)
    return r, theta


def feature_names() -> list[str]:
    names = ["fail_rate"]
    names += [f"radial_{i}" for i in range(N_RADIAL)]
    names += ["edge_sector_max", "edge_sector_std", "edge_sector_maxmin",
              "inner_sector_max", "inner_sector_std"]
    names += ["n_clusters", "largest_frac", "largest_radius", "largest_elong",
              "largest_fill", "top3_frac", "fail_radius_mean", "fail_radius_std"]
    return names


def wafer_features(x: np.ndarray) -> np.ndarray:
    """Features for one map encoded as (2, H, W): [inside wafer, failing die]."""
    inside, fail = x[0] > 0.5, x[1] > 0.5
    size = inside.shape[0]
    r, theta = _polar(size)
    n_in = max(inside.sum(), 1)
    n_fail = fail.sum()
    feats = [n_fail / n_in]

    # Radial profile, using the wafer's own radius (maps are not all full circles)
    r_max = r[inside].max() if inside.any() else 1.0
    rn = r / r_max
    edges = np.linspace(0, 1.0001, N_RADIAL + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        ring = inside & (rn >= lo) & (rn < hi)
        feats.append(fail[ring].mean() if ring.any() else 0.0)

    # Angular asymmetry: edge band and inner disc separately
    sector = ((theta + np.pi) / (2 * np.pi) * N_SECTORS).astype(int) % N_SECTORS
    for region, keep in ((inside & (rn > 0.7), 3), (inside & (rn <= 0.7), 2)):
        rates = np.array([fail[region & (sector == s)].mean() if (region & (sector == s)).any() else 0.0
                          for s in range(N_SECTORS)])
        vals = [rates.max(), rates.std(), rates.max() - rates.min()]
        feats += vals[:keep]

    # Connected clusters of failing dies (8-connectivity)
    lab, n = ndimage.label(fail, structure=np.ones((3, 3)))
    if n:
        sizes = ndimage.sum(fail, lab, index=np.arange(1, n + 1))
        order = np.argsort(sizes)[::-1]
        big = lab == (order[0] + 1)
        ys, xs = np.nonzero(big)
        cy, cx = ys.mean(), xs.mean()
        c = (size - 1) / 2
        largest_radius = np.hypot(cy - c, cx - c) / (size / 2) / r_max
        if len(ys) > 2:
            ev = np.sort(np.linalg.eigvalsh(np.cov(np.vstack([ys, xs]))))
            elong = np.sqrt(ev[1] / max(ev[0], 1e-3))
        else:
            elong = 1.0
        bbox = (np.ptp(ys) + 1) * (np.ptp(xs) + 1)
        fill = len(ys) / bbox
        feats += [n / n_in, sizes[order[0]] / max(n_fail, 1), largest_radius,
                  min(elong, 50.0), fill, sizes[order[:3]].sum() / max(n_fail, 1)]
        feats += [rn[fail].mean(), rn[fail].std()]
    else:
        feats += [0, 0, 0, 1, 0, 0, 0, 0]
    return np.asarray(feats, dtype=np.float32)


def extract_features(X: np.ndarray) -> np.ndarray:
    return np.stack([wafer_features(x) for x in X])


def train_baseline(F_train: np.ndarray, y_train: np.ndarray, seed: int = 0):
    """Gradient boosting with balanced class weights."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.1, class_weight="balanced",
        early_stopping=True, random_state=seed,
    )
    return clf.fit(F_train, y_train)
