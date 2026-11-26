# Model card: wafer map defect classifier

## Model
Compact CNN (about 290k parameters), input 2 × 64 × 64 (inside wafer, failing die).
Test-time augmentation over 8 orientations: yes.
Temperature scaling T = 0.73; auto-label threshold 0.859.

## Training data
WM-811K, split: official.

## Intended use
First-pass triage of wafer maps to support yield engineers. Wafers below the confidence
threshold go to manual review. Root-cause hints are starting hypotheses, not conclusions.

## Not intended for
Automatic disposition (scrapping or releasing wafers) without human review. Maps from other
fabs, products or test programs without re-validation. Mixed patterns (one class per wafer only).

## Results (test set)
| Metric | Value |
|---|---|
| CNN macro-F1 | 0.748 |
| CNN macro-F1 without test-time augmentation | 0.734 |
| Physical-feature baseline macro-F1 | 0.782 |
| Hybrid (CNN + baseline) macro-F1 | 0.805 |
| Calibration error (ECE) before → after | 0.025 → 0.067 |
| Wafers auto-labelled at 99% target | 71.5% |
| Accuracy on auto-labelled wafers | 92.6% |

```
              precision    recall  f1-score   support

      Center      0.795     0.434     0.561       832
       Donut      0.660     0.719     0.689       146
    Edge-Loc      0.773     0.794     0.784      2772
   Edge-Ring      0.980     0.608     0.751      1126
         Loc      0.642     0.658     0.650      1973
   Near-full      0.883     0.958     0.919        95
      Random      0.819     0.759     0.788       257
     Scratch      0.850     0.566     0.679       693
        none      0.859     0.963     0.908      7536

    accuracy                          0.816     15430
   macro avg      0.807     0.718     0.748     15430
weighted avg      0.819     0.816     0.808     15430
```

## Known limitations
- WM-811K labels come from one source and contain some disagreement between similar classes (Loc vs Edge-Loc).
- The 'none' class is down-sampled for training; real production class frequencies differ.
- Calibration was fitted on a held-out split of the same dataset; recalibrate on new data.
