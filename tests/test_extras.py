import numpy as np
import torch

from wafermap.data import CLASSES, iter_lots, prepare_arrays
from wafermap.features import extract_features, feature_names
from wafermap.synthetic import make_dataframe
from wafermap.triage import synthetic_lots
from wafermap.uncertainty import (choose_threshold, expected_calibration_error,
                                  fit_temperature, softmax)


def test_features_shape_and_rotation_invariance():
    X, _ = prepare_arrays(make_dataframe(n_per_class=1, seed=1), size=64)
    F = extract_features(X)
    assert F.shape == (len(CLASSES), len(feature_names()))
    assert np.isfinite(F).all()
    # Rotating a map by 90 degrees should barely change the features
    F_rot = extract_features(np.rot90(X, 1, axes=(2, 3)).copy())
    assert np.allclose(F[:, 0], F_rot[:, 0])  # fail rate exactly
    assert np.allclose(F[:, 1:9], F_rot[:, 1:9], atol=0.05)  # radial profile


def test_temperature_scaling_fixes_overconfidence():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 2000)
    logits = rng.normal(0, 1, (2000, 3))
    logits[np.arange(2000), y] += 1.0
    logits *= 5  # make the model overconfident
    t = fit_temperature(logits, y)
    assert t > 1
    assert expected_calibration_error(softmax(logits, t), y) < expected_calibration_error(softmax(logits), y)


def test_threshold_reaches_target():
    probs = np.array([[0.99, 0.01], [0.9, 0.1], [0.6, 0.4], [0.55, 0.45]])
    y = np.array([0, 0, 1, 0])
    thr = choose_threshold(probs, y, target_accuracy=1.0)
    assert thr == 0.9


def test_iter_lots_groups_wafers():
    df = synthetic_lots(wafers_per_lot=3)
    lots = list(iter_lots(df, size=32))
    assert len(lots) == df["lotName"].nunique()
    name, X, idx = lots[0]
    assert X.shape == (3, 2, 32, 32) and list(idx) == [1, 2, 3]


def test_tta_is_rotation_invariant():
    from wafermap.model import WaferCNN
    from wafermap.uncertainty import tta_logits

    torch.manual_seed(0)
    model = WaferCNN().eval()
    x = torch.rand(2, 2, 32, 32)
    a = tta_logits(model, x)
    b = tta_logits(model, torch.rot90(x, 1, dims=(-2, -1)))
    assert torch.allclose(a, b, atol=1e-5)


def test_cache_roundtrip_and_old_cache_is_rebuilt(tmp_path, monkeypatch):
    import pandas as pd
    from wafermap.data import load_dataset
    from wafermap.synthetic import make_wafer

    monkeypatch.chdir(tmp_path)
    rng = np.random.default_rng(0)
    rows = [{"waferMap": make_wafer(c, rng), "lotName": "lot1", "waferIndex": i + 1.0,
             "failureType": np.array([[c]]), "trianTestLabel": np.array([["Training" if i % 2 else "Test"]])}
            for i, c in enumerate(CLASSES)]
    pkl = tmp_path / "LSWMD.pkl"
    pd.DataFrame(rows).to_pickle(pkl)

    # A cache from an older version stored 'split' as an object array
    np.savez_compressed(tmp_path / "LSWMD_labeled_32.npz", X=np.zeros((1, 2, 32, 32), np.uint8),
                        y=np.zeros(1), split=np.array(["Test"], dtype=object))
    X, y, split = load_dataset(pkl, size=32)
    assert len(y) == len(CLASSES) and set(split) == {"Training", "Test"}
    X2, y2, split2 = load_dataset(pkl, size=32)  # now from the new cache
    assert (y2 == y).all() and split2.dtype.kind == "U"
