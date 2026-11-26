import numpy as np
import pandas as pd
import torch

from wafermap.data import CLASSES, clean_labels, prepare_arrays, resize_map
from wafermap.explain import grad_cam
from wafermap.model import WaferCNN
from wafermap.synthetic import make_dataframe, make_wafer


def test_resize_keeps_discrete_values():
    w = make_wafer("Scratch", np.random.default_rng(0))
    r = resize_map(w, 64)
    assert r.shape == (64, 64)
    assert set(np.unique(r)) <= {0, 1, 2}


def test_clean_labels_handles_wm811k_format():
    df = pd.DataFrame({
        "waferMap": [np.ones((5, 5))] * 3,
        "failureType": [np.array([["Center"]]), np.array([]), np.array([["none"]])],
    })
    out = clean_labels(df)
    assert out["failureType"].tolist() == ["Center", "none"]
    assert out["label"].tolist() == [CLASSES.index("Center"), CLASSES.index("none")]


def test_model_and_gradcam_shapes():
    X, y = prepare_arrays(make_dataframe(n_per_class=2), size=64)
    assert X.shape == (2 * len(CLASSES), 2, 64, 64) and X.dtype == np.uint8
    model = WaferCNN()
    assert model(torch.from_numpy(X[:4]).float()).shape == (4, len(CLASSES))
    cam, pred = grad_cam(model, torch.from_numpy(X[0]).float())
    assert cam.shape == (64, 64) and 0 <= pred < len(CLASSES)
