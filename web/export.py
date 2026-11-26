"""Export the trained model for the in-browser demo.

Writes ``model.onnx`` and ``config.json`` next to ``index.html``. The ONNX
graph returns the logits and the class activation maps (CAM): with global
average pooling followed by one linear layer, CAM is exact and needs no
gradients, so it can run in the browser.

    python web/export.py --model models --out web
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wafermap.data import CLASSES  # noqa: E402
from wafermap.model import WaferCNN  # noqa: E402
from wafermap.rootcause import ROOT_CAUSES  # noqa: E402


class WithCAM(nn.Module):
    def __init__(self, model: WaferCNN):
        super().__init__()
        self.model = model
        self.fc = model.head[-1]

    def forward(self, x):
        feats = self.model.features(x)              # (B, K, h, w)
        logits = self.model.head(feats)             # (B, C)
        cams = torch.einsum("ck,bkhw->bchw", self.fc.weight, feats)
        return logits, cams


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path("models"))
    ap.add_argument("--out", type=Path, default=Path("web"))
    args = ap.parse_args(argv)

    meta = json.loads((args.model / "meta.json").read_text())
    model = WaferCNN(n_classes=len(CLASSES))
    model.load_state_dict(torch.load(args.model / "wafer_cnn.pt", map_location="cpu"))
    model.eval()
    size = meta["size"]

    torch.onnx.export(
        WithCAM(model).eval(), torch.zeros(1, 2, size, size), args.out / "model.onnx",
        input_names=["x"], output_names=["logits", "cams"],
        dynamic_axes={"x": {0: "batch"}, "logits": {0: "batch"}, "cams": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    config = {
        "classes": CLASSES, "size": size, "data": meta["data"],
        "temperature": meta["temperature"], "threshold": meta["threshold"],
        "tta": meta.get("tta", False), "metrics": meta.get("metrics", {}),
        "root_causes": ROOT_CAUSES,
    }
    (args.out / "config.json").write_text(json.dumps(config, indent=1))
    print("Wrote", args.out / "model.onnx", "and", args.out / "config.json")


if __name__ == "__main__":
    main()
