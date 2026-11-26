"""Load a trained model and classify wafer maps, with calibrated confidence."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from .data import CLASSES, resize_map, to_channels
from .explain import grad_cam
from .model import WaferCNN
from .uncertainty import softmax, tta_logits


class WaferClassifier:
    def __init__(self, model_dir: str | Path):
        model_dir = Path(model_dir)
        self.meta = json.loads((model_dir / "meta.json").read_text())
        self.size = self.meta["size"]
        self.temperature = self.meta["temperature"]
        self.threshold = self.meta["threshold"]
        self.tta = self.meta.get("tta", False)
        self.model = WaferCNN(n_classes=len(CLASSES))
        self.model.load_state_dict(torch.load(model_dir / "wafer_cnn.pt", map_location="cpu"))
        self.model.eval()

    def encode(self, wafer: np.ndarray) -> np.ndarray:
        """Raw 0/1/2 map of any shape -> (2, size, size) input."""
        return to_channels(resize_map(np.asarray(wafer), self.size))

    @torch.no_grad()
    def predict_proba(self, X: np.ndarray, batch_size: int = 512) -> np.ndarray:
        run = (lambda xb: tta_logits(self.model, xb)) if self.tta else self.model
        logits = [run(torch.from_numpy(X[i:i + batch_size]).float()).numpy()
                  for i in range(0, len(X), batch_size)]
        return softmax(np.concatenate(logits), self.temperature)

    def explain(self, x: np.ndarray):
        return grad_cam(self.model, torch.from_numpy(x).float())

    def needs_review(self, probs: np.ndarray) -> np.ndarray:
        return probs.max(1) < self.threshold
