"""Synthetic wafer maps for tests and quick demos.

These are *not* a substitute for real data. They let you check the whole
pipeline (preprocessing -> training -> evaluation -> Grad-CAM) in a couple of
minutes before downloading WM-811K. Every map uses the same 0/1/2 encoding as
WM-811K and comes in a random grid size, as real maps do.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import CLASSES


def _grid(n: int):
    c = (n - 1) / 2
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(yy - c, xx - c) / (n / 2)  # 0 at the centre, 1 at the edge
    theta = np.arctan2(yy - c, xx - c)
    return r, theta, yy, xx


def _pattern(kind: str, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return the probability that each die fails for one defect class."""
    r, theta, yy, xx = _grid(n)
    # Real maps vary a lot in background yield loss and in how strong a pattern is
    p = np.full((n, n), rng.uniform(0.01, 0.10))
    amp = rng.uniform(0.45, 0.95)

    def arc(min_cover: float) -> np.ndarray:
        """Angular window: rings are often incomplete on real wafers."""
        cover = rng.uniform(min_cover, 1.0) * np.pi
        dt = np.angle(np.exp(1j * (theta - rng.uniform(-np.pi, np.pi))))
        return np.abs(dt) <= cover

    if kind == "Center":
        p += amp * (r < rng.uniform(0.15, 0.4))
    elif kind == "Donut":
        r0 = rng.uniform(0.35, 0.6)
        p += amp * ((np.abs(r - r0) < rng.uniform(0.07, 0.15)) & arc(0.6))
    elif kind == "Edge-Ring":
        p += amp * ((r > rng.uniform(0.8, 0.9)) & arc(0.6))
    elif kind == "Edge-Loc":
        t0 = rng.uniform(-np.pi, np.pi)
        dt = np.angle(np.exp(1j * (theta - t0)))
        p += amp * ((r > rng.uniform(0.7, 0.8)) & (np.abs(dt) < rng.uniform(0.25, 0.8)))
    elif kind == "Loc":
        cy, cx = rng.uniform(0.3, 0.7, size=2) * n
        rad = rng.uniform(0.08, 0.15) * n
        p += amp * (np.hypot(yy - cy, xx - cx) < rad)
    elif kind == "Near-full":
        p += rng.uniform(0.6, 0.9)
    elif kind == "Random":
        p += rng.uniform(0.12, 0.35)
    elif kind == "Scratch":
        ang = rng.uniform(0, np.pi)
        y0, x0 = rng.uniform(0.3, 0.7, size=2) * n
        # distance from a line, limited to a segment
        d_line = np.abs((yy - y0) * np.cos(ang) - (xx - x0) * np.sin(ang))
        along = (yy - y0) * np.sin(ang) + (xx - x0) * np.cos(ang)
        p += amp * ((d_line < rng.uniform(0.7, 1.4)) & (np.abs(along) < rng.uniform(0.25, 0.45) * n))
    elif kind != "none":
        raise ValueError(f"unknown class {kind!r}")
    return np.clip(p, 0, 1)


def make_wafer(kind: str, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    n = int(rng.integers(26, 60))
    r, *_ = _grid(n)
    inside = r <= 1.0
    fail = rng.random((n, n)) < _pattern(kind, n, rng)
    wafer = np.zeros((n, n), dtype=np.uint8)
    wafer[inside] = 1
    wafer[inside & fail] = 2
    return wafer


def make_dataframe(n_per_class: int = 200, seed: int = 0) -> pd.DataFrame:
    """A DataFrame with the same columns the pipeline expects from WM-811K."""
    rng = np.random.default_rng(seed)
    rows = []
    for i, kind in enumerate(CLASSES):
        for _ in range(n_per_class):
            rows.append({"waferMap": make_wafer(kind, rng), "failureType": kind, "label": i})
    return pd.DataFrame(rows).sample(frac=1, random_state=seed).reset_index(drop=True)
