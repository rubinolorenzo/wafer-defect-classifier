"""Calibrated confidence and a "send to an engineer" option.

In a fab, a wrong automatic label costs more than asking a human. So the useful
question is not "what is the accuracy?" but "if the model labels only the wafers
it is sure about, how many can it handle and how often is it right?"

1. Temperature scaling (Guo et al., 2017) makes the softmax probabilities honest.
2. A confidence threshold is chosen on the validation set to hit a target
   precision; wafers below it are flagged for manual review.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F


def dihedral(x: torch.Tensor):
    """The 8 rotations/reflections of a square map (the symmetries of the grid)."""
    for flip in (False, True):
        xf = torch.flip(x, dims=(-1,)) if flip else x
        for k in range(4):
            yield torch.rot90(xf, k, dims=(-2, -1))


@torch.no_grad()
def tta_logits(model, xb: torch.Tensor) -> torch.Tensor:
    """Test-time augmentation: average the logits over the 8 orientations.

    A defect class does not depend on how the wafer is rotated, so the model
    should not either. Averaging enforces that and smooths out unlucky
    predictions on a single orientation.
    """
    return torch.stack([model(v) for v in dihedral(xb)]).mean(0)


@torch.no_grad()
def collect_logits(model, loader, tta: bool = False) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    device = next(model.parameters()).device
    logits, ys = [], []
    for xb, yb in loader:
        xb = xb.to(device)
        logits.append((tta_logits(model, xb) if tta else model(xb)).cpu())
        ys.append(yb)
    return torch.cat(logits).numpy(), torch.cat(ys).numpy()


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Single scalar T > 0 that minimises the validation negative log-likelihood."""
    lg = torch.from_numpy(logits).float()
    yt = torch.from_numpy(y).long()
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(lg / log_t.exp(), yt)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.detach().exp())


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits / temperature
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def expected_calibration_error(probs: np.ndarray, y: np.ndarray, n_bins: int = 15) -> float:
    conf = probs.max(1)
    correct = probs.argmax(1) == y
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


def coverage_curve(probs: np.ndarray, y: np.ndarray):
    """Accuracy on the auto-labelled wafers vs. the fraction auto-labelled."""
    conf = probs.max(1)
    order = np.argsort(-conf)
    correct = (probs.argmax(1) == y)[order]
    n = np.arange(1, len(y) + 1)
    return n / len(y), np.cumsum(correct) / n, conf[order]


def choose_threshold(probs: np.ndarray, y: np.ndarray, target_accuracy: float = 0.99) -> float:
    """Lowest confidence threshold whose auto-labelled set reaches the target accuracy."""
    coverage, acc, conf = coverage_curve(probs, y)
    ok = np.flatnonzero(acc >= target_accuracy)
    if len(ok) == 0:
        return 1.0  # nothing can be automated at this target
    return float(conf[ok.max()])
