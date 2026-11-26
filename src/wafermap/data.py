"""Loading and preprocessing of the WM-811K wafer map dataset.

WM-811K (Wu et al., IEEE Trans. Semicond. Manuf., 2015) is distributed as a
pickled pandas DataFrame, usually named ``LSWMD.pkl``. Each row holds:

* ``waferMap``   - 2-D array: 0 = outside the wafer, 1 = good die, 2 = failing die
* ``failureType`` - nested array such as ``[['Edge-Ring']]``, or empty if unlabeled
* ``trianTestLabel`` (sic) - original train/test split, same nested format
* ``dieSize``, ``lotName``, ``waferIndex``

Only about 20 % of the wafers carry a label, and the classes are very
imbalanced (most labeled wafers are ``none``).
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CLASSES = [
    "Center",
    "Donut",
    "Edge-Loc",
    "Edge-Ring",
    "Loc",
    "Near-full",
    "Random",
    "Scratch",
    "none",
]
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}


def load_lswmd(path: str | Path) -> pd.DataFrame:
    """Read ``LSWMD.pkl``.

    The file was written with an old pandas under Python 2, so a plain
    ``pd.read_pickle`` can fail on recent versions. In that case we alias the
    old module paths and fall back to ``pickle`` with latin-1 decoding.
    """
    path = Path(path)
    try:
        return pd.read_pickle(path)
    except Exception:
        import pandas.core.indexes as _idx

        sys.modules.setdefault("pandas.indexes", _idx)
        for name in ("base", "range", "numeric", "multi"):
            mod = getattr(_idx, name, None)
            if mod is not None:
                sys.modules.setdefault(f"pandas.indexes.{name}", mod)
        with open(path, "rb") as fh:
            return pickle.load(fh, encoding="latin1")


def _unwrap_label(value) -> str | None:
    """Turn ``[['Edge-Ring']]`` into ``'Edge-Ring'`` and empty arrays into None."""
    arr = np.asarray(value, dtype=object).ravel()
    if arr.size == 0:
        return None
    label = str(arr[0]).strip()
    return label or None


def clean_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only labeled wafers and add an integer ``label`` column."""
    # Filter before copying: the full table has 811k rows, the labeled part ~170k
    labels = df["failureType"].map(_unwrap_label)
    keep = labels.isin(CLASSES)
    out = df.loc[keep].copy()
    out["failureType"] = labels[keep]
    if "trianTestLabel" in out:  # original split; the typo is in the dataset
        out["split"] = out["trianTestLabel"].map(_unwrap_label)
    out = out[out["failureType"].isin(CLASSES)].reset_index(drop=True)
    out["label"] = out["failureType"].map(CLASS_TO_IDX).astype(int)
    return out


def resize_map(wafer: np.ndarray, size: int = 64) -> np.ndarray:
    """Nearest-neighbour resize that keeps the discrete values 0/1/2.

    Wafer maps come in hundreds of different shapes (they depend on die size);
    interpolation would invent fractional values that have no physical meaning,
    so we sample the nearest die instead.
    """
    wafer = np.asarray(wafer)
    h, w = wafer.shape
    rows = np.minimum((np.arange(size) + 0.5) * h / size, h - 1).astype(int)
    cols = np.minimum((np.arange(size) + 0.5) * w / size, w - 1).astype(int)
    return wafer[np.ix_(rows, cols)]


def to_channels(wafer: np.ndarray) -> np.ndarray:
    """Encode a 0/1/2 map as two binary channels: [inside wafer, failing die]."""
    inside = (wafer > 0).astype(np.float32)
    fail = (wafer == 2).astype(np.float32)
    return np.stack([inside, fail])


def prepare_arrays(df: pd.DataFrame, size: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Return ``X`` with shape (N, 2, size, size) and integer labels ``y``.

    ``X`` is stored as uint8 (0/1): four times less memory than float32, which
    matters with ~170k labeled wafers on a 16 GB laptop. Convert batches to
    float only when they go into the model.
    """
    X = np.empty((len(df), 2, size, size), dtype=np.uint8)
    for i, w in enumerate(df["waferMap"]):
        X[i] = to_channels(resize_map(w, size))
    y = df["label"].to_numpy()
    return X, y


def load_dataset(path: str | Path, size: int = 64, cache: bool = True):
    """Load, clean and resize the labeled part of WM-811K.

    Returns ``X``, ``y`` and ``split`` (the original "Training"/"Test" tag per
    wafer). The result is cached as ``.npz`` next to the pickle.
    """
    path = Path(path)
    name = f"{path.stem}_labeled_{size}.npz"
    # Next to the pickle if possible; otherwise (e.g. read-only /kaggle/input) in the current folder
    candidates = [path.parent / name, Path.cwd() / name]
    if cache:
        for cache_file in candidates:
            if cache_file.exists():
                try:
                    with np.load(cache_file, allow_pickle=False) as data:
                        return data["X"], data["y"], data["split"]
                except (ValueError, OSError, KeyError) as err:
                    # e.g. a cache written by an older version of this code
                    print(f"Ignoring unreadable cache {cache_file} ({err}); rebuilding it.")
                    try:
                        cache_file.unlink()
                    except OSError:
                        pass
    import gc

    print(f"Reading {path.name} (first run only, takes a few minutes)...")
    raw = load_lswmd(path)
    df = clean_labels(raw)
    del raw
    gc.collect()
    print(f"Converting {len(df)} labeled wafer maps to {size}x{size}...")
    X, y = prepare_arrays(df, size)
    # Fixed-width text, never an object array, so the cache loads without pickle
    split = (np.asarray(df["split"].fillna("").astype(str).tolist(), dtype="U8") if "split" in df
             else np.full(len(y), "", dtype="U8"))
    if cache:
        for cache_file in candidates:
            try:
                np.savez_compressed(cache_file, X=X, y=y, split=split)
                print(f"Cached converted maps in {cache_file}")
                break
            except OSError:
                continue
    return X, y, split


def iter_lots(df: pd.DataFrame, size: int = 64, lots: list[str] | None = None, max_lots: int | None = None):
    """Yield ``(lot_name, X, wafer_index)`` for every lot, labeled or not.

    Converting all 811k maps at once would need tens of GB of memory, so lots
    are processed one at a time.
    """
    names = lots if lots else list(dict.fromkeys(df["lotName"]))
    if max_lots:
        names = names[:max_lots]
    for lot in names:
        sub = df[df["lotName"] == lot]
        if sub.empty:
            continue
        X = np.stack([to_channels(resize_map(w, size)) for w in sub["waferMap"]])
        yield lot, X, sub["waferIndex"].to_numpy()
