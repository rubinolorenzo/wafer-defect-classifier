"""Lot triage: what a yield engineer would want on Monday morning.

About 80 % of WM-811K has no label, which is the realistic situation in a
fab. This script runs the trained model on whole lots, labeled or not, and
writes one Markdown report with, for each lot:

* how many wafers show each pattern,
* which wafers the model is unsure about (to review by hand),
* the stacked failure map of the lot (systematic problems add up, random ones
  average out),
* the process hypotheses for the dominant pattern.

Example::

    python -m wafermap.triage --data data/LSWMD.pkl --model outputs --max-lots 20
    python -m wafermap.triage --synthetic --model outputs
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .data import CLASSES, iter_lots, load_lswmd
from .predict import WaferClassifier
from .rootcause import ROOT_CAUSES
from .synthetic import make_wafer

PATTERN_LOTS = ["Edge-Ring", "Center", "Scratch", "none"]  # for the synthetic demo


def synthetic_lots(seed: int = 0, wafers_per_lot: int = 25) -> pd.DataFrame:
    """Demo lots: each lot has one systematic problem plus clean wafers."""
    rng = np.random.default_rng(seed)
    rows = []
    for i, kind in enumerate(PATTERN_LOTS):
        for w in range(wafers_per_lot):
            k = kind if rng.random() < 0.6 else "none"
            rows.append({"lotName": f"DEMO{i + 1:03d}", "waferIndex": w + 1, "waferMap": make_wafer(k, rng)})
    return pd.DataFrame(rows)


def lot_figure(X: np.ndarray, path: Path, title: str):
    inside = X[:, 0].mean(0)
    fail_rate = np.where(inside > 0, X[:, 1].sum(0) / np.maximum(X[:, 0].sum(0), 1), np.nan)
    fig, ax = plt.subplots(figsize=(3.2, 3.2))
    im = ax.imshow(fail_rate, cmap="magma", vmin=0, vmax=max(np.nanmax(fail_rate), 0.05))
    ax.set_title(title, fontsize=9)
    ax.axis("off")
    fig.colorbar(im, ax=ax, fraction=0.046, label="Fail rate per die")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def triage_lot(clf: WaferClassifier, lot: str, X: np.ndarray, idx: np.ndarray, fig_dir: Path) -> tuple[str, dict]:
    probs = clf.predict_proba(X)
    pred = probs.argmax(1)
    review = clf.needs_review(probs)
    counts = Counter(CLASSES[p] for p, r in zip(pred, review) if not r)
    defect_counts = {k: v for k, v in counts.items() if k != "none"}
    dominant = max(defect_counts, key=defect_counts.get) if defect_counts else "none"
    yield_pct = 100 * (1 - X[:, 1].sum() / max(X[:, 0].sum(), 1))

    fig_name = f"{lot}.png"
    lot_figure(X, fig_dir / fig_name, f"Lot {lot}: stacked fail rate")

    lines = [f"## Lot {lot}", "",
             f"**{len(X)} wafers** · die yield {yield_pct:.1f}% · dominant pattern: **{dominant}**", "",
             f"![stacked map]({fig_dir.name}/{fig_name})", "",
             "| Pattern | Wafers |", "|---|---|"]
    for name in CLASSES:
        if counts.get(name):
            lines.append(f"| {name} | {counts[name]} |")
    if review.any():
        lines.append(f"| *needs review* | {int(review.sum())} |")
    lines.append("")
    if dominant != "none":
        rc = ROOT_CAUSES[dominant]
        lines += [f"**Hypotheses:** {rc['hypotheses']}", "", f"**Check first:** {rc['check']}", ""]
    if review.any():
        lines.append("Wafers to review by hand: " + ", ".join(str(int(w)) for w in idx[review]))
        lines.append("")
    summary = {"lot": lot, "wafers": len(X), "yield": yield_pct, "dominant": dominant,
               "review": int(review.sum())}
    return "\n".join(lines), summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", type=Path, help="path to LSWMD.pkl")
    src.add_argument("--synthetic", action="store_true")
    ap.add_argument("--model", type=Path, default=Path("outputs"), help="folder with wafer_cnn.pt and meta.json")
    ap.add_argument("--lots", nargs="*", help="lot names to analyse (default: all)")
    ap.add_argument("--max-lots", type=int, default=20)
    ap.add_argument("--out", type=Path, default=Path("outputs/triage"))
    args = ap.parse_args(argv)

    clf = WaferClassifier(args.model)
    df = synthetic_lots() if args.synthetic else load_lswmd(args.data)
    args.out.mkdir(parents=True, exist_ok=True)
    fig_dir = args.out / "lots"
    fig_dir.mkdir(exist_ok=True)

    sections, summaries = [], []
    for lot, X, idx in iter_lots(df, clf.size, args.lots, args.max_lots):
        text, summary = triage_lot(clf, lot, X, idx, fig_dir)
        sections.append(text)
        summaries.append(summary)
        print(f"{lot}: {summary['dominant']:<10} yield {summary['yield']:.1f}%  review {summary['review']}")

    # Lots with a systematic pattern first, worst yield first
    order = sorted(range(len(summaries)), key=lambda i: (summaries[i]["dominant"] == "none", summaries[i]["yield"]))
    head = ["# Lot triage report", "",
            f"Model trained on: {clf.meta['data']} · auto-label threshold {clf.threshold:.2f} "
            f"(target accuracy {clf.meta['target_accuracy']:.0%})", "",
            "| Lot | Wafers | Die yield | Dominant pattern | To review |", "|---|---|---|---|---|"]
    for i in order:
        s = summaries[i]
        head.append(f"| {s['lot']} | {s['wafers']} | {s['yield']:.1f}% | {s['dominant']} | {s['review']} |")
    report = "\n".join(head + [""] + [sections[i] for i in order])
    (args.out / "report.md").write_text(report)
    print(f"Report written to {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
