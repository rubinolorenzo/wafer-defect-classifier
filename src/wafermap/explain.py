"""Grad-CAM: which dies drove the model's decision?

For a process engineer this is the useful part. A model that calls a wafer
"Edge-Ring" while looking at the centre is wrong for the wrong reason, even if
the label happens to match.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

from .model import WaferCNN


def grad_cam(model: WaferCNN, x: torch.Tensor, target: int | None = None) -> tuple[np.ndarray, int]:
    """Return a heat map in [0, 1] with the input's spatial size, and the class used."""
    model.eval()
    feats, grads = {}, {}
    layer = model.last_conv
    h1 = layer.register_forward_hook(lambda m, i, o: feats.__setitem__("a", o))
    h2 = layer.register_full_backward_hook(lambda m, gi, go: grads.__setitem__("g", go[0]))
    try:
        x = x.unsqueeze(0) if x.dim() == 3 else x
        logits = model(x)
        target = int(logits.argmax(1)) if target is None else target
        model.zero_grad()
        logits[0, target].backward()
    finally:
        h1.remove()
        h2.remove()
    weights = grads["g"].mean(dim=(2, 3), keepdim=True)
    cam = F.relu((weights * feats["a"]).sum(1, keepdim=True))
    cam = F.interpolate(cam, size=x.shape[-2:], mode="bilinear", align_corners=False)[0, 0]
    cam = cam.detach().numpy()
    cam -= cam.min()
    if cam.max() > 0:
        cam /= cam.max()
    return cam * x[0, 0].numpy(), target  # mask outside the wafer
