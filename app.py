"""Interactive demo, ready for Hugging Face Spaces.

Run locally with ``python app.py``. It expects ``models/wafer_cnn.pt`` and
``models/meta.json``, i.e. the files that ``wafermap.train`` writes to its
output folder.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import gradio as gr
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))
from wafermap.data import CLASSES  # noqa: E402
from wafermap.predict import WaferClassifier  # noqa: E402
from wafermap.rootcause import ROOT_CAUSES  # noqa: E402
from wafermap.synthetic import make_wafer  # noqa: E402

MODEL_DIR = Path(os.environ.get("MODEL_DIR", Path(__file__).parent / "models"))
clf = WaferClassifier(MODEL_DIR)


def _figure(img, cmap, title, vmin=0, vmax=None):
    fig, ax = plt.subplots(figsize=(3.4, 3.4))
    ax.imshow(img, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title, fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    return fig


def _load_upload(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        wafer = np.load(path, allow_pickle=False)
    else:
        wafer = np.loadtxt(path, delimiter="," if path.endswith(".csv") else None)
    wafer = np.asarray(wafer).astype(int)
    if wafer.ndim != 2 or not set(np.unique(wafer)) <= {0, 1, 2}:
        raise gr.Error("Expected a 2-D map with values 0 (outside), 1 (good die), 2 (failing die).")
    return wafer


def analyse(wafer: np.ndarray):
    x = clf.encode(wafer)
    probs = clf.predict_proba(x[None])[0]
    cam, pred = clf.explain(x)
    name = CLASSES[pred]
    conf = float(probs.max())

    if conf < clf.threshold:
        verdict = (f"### ⚠️ Send to an engineer\nConfidence {conf:.1%} is below the auto-label "
                   f"threshold ({clf.threshold:.1%}). Best guess: **{name}**.")
    else:
        verdict = f"### {name}\nConfidence {conf:.1%}, above the auto-label threshold ({clf.threshold:.1%})."
    rc = ROOT_CAUSES[name]
    text = (f"{verdict}\n\n**Process hypotheses:** {rc['hypotheses']}\n\n**Check first:** {rc['check']}\n\n"
            f"<small>Model trained on {clf.meta['data']}. Hypotheses are starting points for "
            f"root-cause analysis, not conclusions.</small>")

    wafer_img = x[0] + x[1]
    return (_figure(wafer_img, "viridis", "Wafer map (yellow = failing die)", vmax=2),
            _figure(cam, "inferno", "Where the model looked (Grad-CAM)", vmax=1),
            {c: float(p) for c, p in zip(CLASSES, probs)},
            text)


def from_example(kind: str):
    return analyse(make_wafer(kind, np.random.default_rng()))


def from_upload(file):
    if file is None:
        raise gr.Error("Upload a .npy or .csv wafer map first.")
    return analyse(_load_upload(file if isinstance(file, str) else file.name))


with gr.Blocks(title="Wafer map defect classifier") as demo:
    gr.Markdown(
        "# Wafer map defect classifier\n"
        "Recognises 9 failure patterns on semiconductor wafer maps, shows where the model looked, "
        "flags uncertain wafers for an engineer, and suggests which process step to investigate."
    )
    with gr.Row():
        with gr.Column(scale=1):
            kind = gr.Dropdown(CLASSES, value="Edge-Ring", label="Generate an example pattern")
            btn = gr.Button("Generate and classify", variant="primary")
            upload = gr.File(label="…or upload your own map (.npy / .csv, values 0/1/2)",
                             file_types=[".npy", ".csv", ".txt"])
            btn_up = gr.Button("Classify upload")
        with gr.Column(scale=2):
            with gr.Row():
                wafer_plot = gr.Plot(label="Wafer")
                cam_plot = gr.Plot(label="Grad-CAM")
            probs = gr.Label(num_top_classes=4, label="Calibrated probabilities")
    verdict = gr.Markdown()
    outputs = [wafer_plot, cam_plot, probs, verdict]
    btn.click(from_example, kind, outputs)
    btn_up.click(from_upload, upload, outputs)

if __name__ == "__main__":
    demo.launch()
