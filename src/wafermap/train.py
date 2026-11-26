"""Train, calibrate and evaluate the wafer map classifier.

Examples
--------
Quick check on synthetic data (a few minutes on a CPU)::

    python -m wafermap.train --synthetic --epochs 6

Real data, after downloading ``LSWMD.pkl`` into ``data/``::

    python -m wafermap.train --data data/LSWMD.pkl --epochs 20 --split official

Outputs (in ``--out``): model weights, ``meta.json`` (calibration and metrics),
``test_report.txt`` and figures for the README.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .data import CLASSES, load_dataset, prepare_arrays
from .explain import grad_cam
from .features import extract_features, train_baseline
from .model import WaferCNN
from .synthetic import make_dataframe
from .uncertainty import (choose_threshold, collect_logits, coverage_curve,
                          expected_calibration_error, fit_temperature, softmax)


def augment(x: torch.Tensor) -> torch.Tensor:
    """Random 90-degree rotations and flips.

    Defect classes on a round wafer do not depend on orientation, so this is
    physically safe and helps the rare classes a lot.
    """
    k = int(torch.randint(0, 4, (1,)))
    x = torch.rot90(x, k, dims=(-2, -1))
    if torch.rand(1) < 0.5:
        x = torch.flip(x, dims=(-1,))
    return x


def downsample_none(X, y, split, max_none: int | None, seed: int):
    """Cap the dominant 'none' class so training is not swamped by it."""
    if not max_none:
        return X, y, split
    none_idx = np.flatnonzero(y == CLASSES.index("none"))
    if len(none_idx) <= max_none:
        return X, y, split
    rng = np.random.default_rng(seed)
    drop = rng.choice(none_idx, len(none_idx) - max_none, replace=False)
    keep = np.setdiff1d(np.arange(len(y)), drop)
    return X[keep], y[keep], split[keep]


def make_splits(X, y, split, mode: str, seed: int):
    """70/15/15 stratified split, or the dataset's own Training/Test split."""
    if mode == "official":
        tr, te = split == "Training", split == "Test"
        if not tr.any() or not te.any():
            raise SystemExit("No original split found in the data; use --split random.")
        X_tr, X_va, y_tr, y_va = train_test_split(X[tr], y[tr], test_size=0.15, stratify=y[tr], random_state=seed)
        return X_tr, X_va, X[te], y_tr, y_va, y[te]
    X_tr, X_tmp, y_tr, y_tmp = train_test_split(X, y, test_size=0.3, stratify=y, random_state=seed)
    X_va, X_te, y_va, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, stratify=y_tmp, random_state=seed)
    return X_tr, X_va, X_te, y_tr, y_va, y_te


# ---------------------------------------------------------------- figures

def plot_confusion(cm: np.ndarray, path: Path, title: str = ""):
    cmn = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(CLASSES)), CLASSES, rotation=45, ha="right")
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    if title:
        ax.set_title(title)
    for i in range(len(CLASSES)):
        for j in range(len(CLASSES)):
            if cm[i, j]:
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                        color="white" if cmn[i, j] > 0.5 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, label="Recall per row")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_gradcam_gallery(model, X, y, path: Path):
    """One example per class: the wafer map and where the model looked."""
    fig, axes = plt.subplots(2, len(CLASSES), figsize=(2 * len(CLASSES), 4.4))
    for c, name in enumerate(CLASSES):
        idx = np.flatnonzero(y == c)
        if len(idx) == 0:
            for ax in axes[:, c]:
                ax.axis("off")
            continue
        x = torch.from_numpy(X[idx[0]]).float()
        cam, pred = grad_cam(model, x)
        wafer = X[idx[0], 0].astype(int) + X[idx[0], 1]  # 0 outside, 1 good, 2 fail
        axes[0, c].imshow(wafer, cmap="viridis", vmin=0, vmax=2)
        axes[0, c].set_title(name, fontsize=9)
        axes[1, c].imshow(cam, cmap="inferno", vmin=0, vmax=1)
        axes[1, c].set_title(f"pred: {CLASSES[pred]}", fontsize=8)
        for ax in axes[:, c]:
            ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_coverage(probs, y, threshold, path: Path):
    coverage, acc, conf = coverage_curve(probs, y)
    auto = conf >= threshold
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(coverage * 100, acc * 100, color="#17708a", lw=2)
    if auto.any():
        cov_t = auto.sum() / len(y) * 100
        ax.axvline(cov_t, color="#a86a00", ls="--", lw=1)
        ax.text(cov_t, 0.05, f"threshold: {cov_t:.0f}% auto-labelled  ", transform=ax.get_xaxis_transform(),
                color="#a86a00", fontsize=9, ha="right", va="bottom")
    ax.set_xlabel("Wafers labelled automatically (%)")
    ax.set_ylabel("Accuracy on those wafers (%)")
    ax.set_title("The rest go to an engineer")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_f1_comparison(f1_cnn, f1_base, path: Path):
    xs = np.arange(len(CLASSES))
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(xs - 0.2, f1_base, 0.4, label="Physical features + gradient boosting", color="#a9b8c2")
    ax.bar(xs + 0.2, f1_cnn, 0.4, label="CNN", color="#17708a")
    ax.set_xticks(xs, CLASSES, rotation=30, ha="right")
    ax.set_ylabel("F1 on test set")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=2, fontsize=9, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- model card

def model_card(meta: dict, report: str) -> str:
    """A short model card (Mitchell et al., 2019), filled from this run."""
    m = meta["metrics"]

    def pct(v):
        return "n/a" if v is None else f"{100 * v:.1f}%"

    rows = [("CNN macro-F1", f"{m['cnn_macro_f1']:.3f}")]
    if "cnn_macro_f1_without_tta" in m:
        rows.append(("CNN macro-F1 without test-time augmentation", f"{m['cnn_macro_f1_without_tta']:.3f}"))
    if "baseline_macro_f1" in m:
        rows += [("Physical-feature baseline macro-F1", f"{m['baseline_macro_f1']:.3f}"),
                 ("Hybrid (CNN + baseline) macro-F1", f"{m['hybrid_macro_f1']:.3f}")]
    rows += [("Calibration error (ECE) before → after", f"{m['ece_before']:.3f} → {m['ece_after']:.3f}"),
             (f"Wafers auto-labelled at {meta['target_accuracy']:.0%} target", pct(m["auto_coverage"])),
             ("Accuracy on auto-labelled wafers", pct(m["auto_accuracy"]))]
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"""# Model card: wafer map defect classifier

## Model
Compact CNN (about 290k parameters), input 2 × {meta['size']} × {meta['size']} (inside wafer, failing die).
Test-time augmentation over 8 orientations: {"yes" if meta.get("tta") else "no"}.
Temperature scaling T = {meta['temperature']:.2f}; auto-label threshold {meta['threshold']:.3f}.

## Training data
{meta['data']}, split: {meta['split']}.

## Intended use
First-pass triage of wafer maps to support yield engineers. Wafers below the confidence
threshold go to manual review. Root-cause hints are starting hypotheses, not conclusions.

## Not intended for
Automatic disposition (scrapping or releasing wafers) without human review. Maps from other
fabs, products or test programs without re-validation. Mixed patterns (one class per wafer only).

## Results (test set)
| Metric | Value |
|---|---|
{table}

```
{report}```

## Known limitations
- WM-811K labels come from one source and contain some disagreement between similar classes (Loc vs Edge-Loc).
- The 'none' class is down-sampled for training; real production class frequencies differ.
- Calibration was fitted on a held-out split of the same dataset; recalibrate on new data.
"""


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", type=Path, help="path to LSWMD.pkl")
    src.add_argument("--synthetic", action="store_true", help="use generated maps instead")
    ap.add_argument("--split", choices=["random", "official"], default="random",
                    help="'official' uses the dataset's Training/Test tags, for comparison with papers")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--max-none", type=int, default=10000, help="cap on 'none' wafers (0 = keep all)")
    ap.add_argument("--target-accuracy", type=float, default=0.99,
                    help="accuracy required on auto-labelled wafers")
    ap.add_argument("--n-per-class", type=int, default=300, help="synthetic maps per class")
    ap.add_argument("--no-baseline", action="store_true", help="skip the feature-based baseline")
    ap.add_argument("--no-tta", action="store_true", help="disable test-time augmentation (8 orientations)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.synthetic:
        X, y = prepare_arrays(make_dataframe(args.n_per_class, args.seed), args.size)
        split = np.array([""] * len(y))
        source = f"synthetic ({args.n_per_class} maps per class)"
    else:
        X, y, split = load_dataset(args.data, args.size)
        source = "WM-811K"
    X, y, split = downsample_none(X, y, split, args.max_none, args.seed)
    print("Samples per class:", dict(zip(CLASSES, np.bincount(y, minlength=len(CLASSES)).tolist())))

    X_tr, X_va, X_te, y_tr, y_va, y_te = make_splits(X, y, split, args.split, args.seed)

    def loader(X_, y_, shuffle):
        ds = TensorDataset(torch.from_numpy(X_).float(), torch.from_numpy(y_).long())
        return DataLoader(ds, batch_size=args.batch_size, shuffle=shuffle)

    train_dl, val_dl, test_dl = loader(X_tr, y_tr, True), loader(X_va, y_va, False), loader(X_te, y_te, False)

    # Inverse-sqrt-frequency class weights (full inverse frequency over-corrects)
    counts = np.bincount(y_tr, minlength=len(CLASSES)).astype(float)
    weights = 1 / np.sqrt(np.maximum(counts, 1))
    weights = torch.tensor(weights / weights.mean(), dtype=torch.float32)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Training on", device)
    model = WaferCNN(n_classes=len(CLASSES)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(train_dl))
    loss_fn = nn.CrossEntropyLoss(weight=weights.to(device))

    best_f1, best_state, history = -1.0, None, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        running = 0.0
        for xb, yb in train_dl:
            xb, yb = augment(xb).to(device), yb.to(device)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            sched.step()
            running += loss.item() * len(yb)
        val_logits, _ = collect_logits(model, val_dl)
        f1 = f1_score(y_va, val_logits.argmax(1), average="macro")
        history.append({"epoch": epoch, "train_loss": running / len(y_tr), "val_macro_f1": f1})
        print(f"epoch {epoch:2d}  loss {running / len(y_tr):.4f}  val macro-F1 {f1:.3f}")
        if f1 > best_f1:
            best_f1, best_state = f1, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)

    # --- calibration and reject option, both fitted on validation only
    tta = not args.no_tta
    val_logits, _ = collect_logits(model, val_dl, tta=tta)
    temperature = fit_temperature(val_logits, y_va)
    threshold = choose_threshold(softmax(val_logits, temperature), y_va, args.target_accuracy)

    if tta:  # how much do the 8 orientations help?
        plain_logits, _ = collect_logits(model, test_dl)
        f1_plain = f1_score(y_te, plain_logits.argmax(1), average="macro")
    test_logits, _ = collect_logits(model, test_dl, tta=tta)
    p_raw, p_cal = softmax(test_logits), softmax(test_logits, temperature)
    y_pred = p_cal.argmax(1)
    auto = p_cal.max(1) >= threshold
    labels = list(range(len(CLASSES)))

    report = classification_report(y_te, y_pred, labels=labels, target_names=CLASSES, digits=3, zero_division=0)
    f1_cnn = f1_score(y_te, y_pred, labels=labels, average=None, zero_division=0)
    metrics = {
        "cnn_macro_f1": float(f1_cnn.mean()),
        "cnn_accuracy": float((y_pred == y_te).mean()),
        "ece_before": expected_calibration_error(p_raw, y_te),
        "ece_after": expected_calibration_error(p_cal, y_te),
        "auto_coverage": float(auto.mean()),
        "auto_accuracy": float((y_pred[auto] == y_te[auto]).mean()) if auto.any() else None,
    }
    if tta:
        metrics["cnn_macro_f1_without_tta"] = float(f1_plain)

    # --- interpretable baseline on physical features
    if not args.no_baseline:
        print("Computing physical features for the baseline...")
        base = train_baseline(extract_features(X_tr), y_tr, args.seed)
        pb = np.zeros_like(p_cal)
        pb[:, base.classes_] = base.predict_proba(extract_features(X_te))
        f1_base = f1_score(y_te, pb.argmax(1), labels=labels, average=None, zero_division=0)
        metrics["baseline_macro_f1"] = float(f1_base.mean())
        # Hybrid: average the two opinions. Features and CNN make different mistakes.
        metrics["hybrid_macro_f1"] = float(f1_score(y_te, (p_cal + pb).argmax(1), average="macro"))
        plot_f1_comparison(f1_cnn, f1_base, args.out / "cnn_vs_baseline.png")

    print("\nTest set (CNN)\n" + report)
    print(json.dumps(metrics, indent=2))

    model.cpu()  # saved weights and Grad-CAM work on any machine
    torch.save(model.state_dict(), args.out / "wafer_cnn.pt")
    meta = {
        "classes": CLASSES, "size": args.size, "data": source, "split": args.split,
        "temperature": temperature, "threshold": threshold, "tta": tta, "target_accuracy": args.target_accuracy,
        "metrics": metrics, "history": history,
    }
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2))
    (args.out / "test_report.txt").write_text(report)
    (args.out / "MODEL_CARD.md").write_text(model_card(meta, report))
    plot_confusion(confusion_matrix(y_te, y_pred, labels=labels), args.out / "confusion_matrix.png")
    plot_gradcam_gallery(model, X_te, y_te, args.out / "gradcam_examples.png")
    plot_coverage(p_cal, y_te, threshold, args.out / "coverage_curve.png")
    print(f"Saved model, meta.json, report and figures to {args.out}/")


if __name__ == "__main__":
    main()
