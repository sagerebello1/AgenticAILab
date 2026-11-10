# Out-of-sample acquisition evaluation

Generated 2026-11-10T00:34:03Z.

No predictive accuracy is claimed for screening companies or for option valuation. Acquired companies were sampled at fixed offsets before a known announcement, so the 30-day label is the sampling design. Unread item 1.01 hits (8476) exceed verified transactions (749). Non-acquired labels come from an EDGAR phrase screen, not from a census of companies that stayed independent.

## 30-day holdout

Model: XGBoost (depth 2, 160 trees, lambda 1).
Holdout rows 144, positives 44, negatives 100, positive rate 0.3056.

- PR-AUC: 0.5162. Base rate: 0.3056.
- ROC-AUC: 0.7018. Constant-score ROC-AUC: 0.5000.
- Brier score: 0.1903. Training-rate Brier score: 0.2122.
- Precision / recall at 0.50: 0.6316 / 0.2727.
- Precision / recall at the training positive rate: 0.4681 / 0.5000.
- Precision in the top 10 holdout rows: 0.6000.
- Precision in the top 5 percent (7 rows): 0.7143.

Calibration, lowest predicted score to highest:

- 28 rows, mean predicted 0.1252, observed rate 0.1429
- 28 rows, mean predicted 0.1894, observed rate 0.1429
- 28 rows, mean predicted 0.2422, observed rate 0.2857
- 28 rows, mean predicted 0.3172, observed rate 0.3929
- 32 rows, mean predicted 0.5393, observed rate 0.5312

## 60-day holdout

Not fit. No stored snapshot falls 31 to 60 days before an announcement, so the 60-day label matches the 30-day label on all 786 comparable rows. A separate 60-day probability was not produced.

## 90-day holdout

Model: XGBoost (depth 2, 160 trees, lambda 1).
Holdout rows 142, positives 86, negatives 56, positive rate 0.6056.

- PR-AUC: 0.7668. Base rate: 0.6056.
- ROC-AUC: 0.7830. Constant-score ROC-AUC: 0.5000.
- Brier score: 0.1754. Training-rate Brier score: 0.2392.
- Precision / recall at 0.50: 0.7742 / 0.8372.
- Precision / recall at the training positive rate: 0.8125 / 0.7558.
- Precision in the top 10 holdout rows: 0.5000.
- Precision in the top 5 percent (7 rows): 0.4286.

Calibration, lowest predicted score to highest:

- 28 rows, mean predicted 0.2674, observed rate 0.1071
- 28 rows, mean predicted 0.4579, observed rate 0.5714
- 28 rows, mean predicted 0.6633, observed rate 0.7143
- 28 rows, mean predicted 0.8053, observed rate 0.8214
- 30 rows, mean predicted 0.9121, observed rate 0.8000

## Contributing features for the 30-day model

These are training-sample associations. They are not causes.

- days_since_10k: importance 0.1175
- return_90: importance 0.0638
- volatility_30: importance 0.0628
- abnormal_7: importance 0.0615
- volume_change_7: importance 0.0607
- return_7: importance 0.0592
- abnormal_90: importance 0.0564
- abnormal_30: importance 0.0544

## Highest 30-day scores in the holdout

These are past prediction dates from the holdout, shown with the outcome so the ranking can be checked. They are not current recommendations.

| Rank | Company | Prediction date | Probability | Announced within 30 days | Feature coverage | News observed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Evofem Biosciences, Inc. (EVFM) | 2025-02-24 | 0.7788 | yes | 0.62 | no |
| 2 | Grayscale Stellar Lumens Trust (XLM) (GXLM) | 2024-10-05 | 0.7422 | no | 0.62 | no |
| 3 | SILICON LABORATORIES INC. (SLAB) | 2026-01-05 | 0.7287 | yes | 0.62 | no |
| 4 | Park Hotels & Resorts Inc. (PK) | 2024-02-16 | 0.7121 | no | 0.62 | no |
| 5 | SharpLink Gaming, Inc. (SBET) | 2025-03-04 | 0.6699 | yes | 0.62 | no |
| 6 | DILLARD'S, INC. (DDS) | 2026-02-18 | 0.6460 | yes | 0.75 | no |
| 7 | Capital Bancorp Inc (CBNK) | 2024-03-02 | 0.6442 | yes | 0.62 | no |
| 8 | Reliance Global Group, Inc. (EZRA) | 2026-03-07 | 0.6317 | no | 0.62 | no |
| 9 | Cavitation Technologies, Inc. (CVAT) | 2026-09-13 | 0.6272 | yes | 0.62 | no |
| 10 | FB Financial Corp (FBK) | 2024-12-31 | 0.6266 | no | 0.62 | no |
| 11 | Mission Produce, Inc. (AVO) | 2025-12-16 | 0.5837 | yes | 0.62 | no |
| 12 | ONEOK INC /NEW/ (OKE) | 2026-03-19 | 0.5810 | no | 0.62 | no |
| 13 | GRAN TIERRA ENERGY INC. (GTE) | 2026-01-19 | 0.5802 | yes | 0.62 | no |
| 14 | Chord Energy Corp (CHRD) | 2025-02-12 | 0.5761 | yes | 0.62 | no |
| 15 | OLD SECOND BANCORP INC (OSBC) | 2025-01-26 | 0.5399 | yes | 0.88 | no |

## Valuation link

The predicted probability was not connected to the acquisition-aware valuation. Acquired companies were sampled at fixed offsets before a known announcement, so the 30-day label is the sampling design. Unread item 1.01 hits (8476) exceed verified transactions (749). Non-acquired labels come from an EDGAR phrase screen, not from a census of companies that stayed independent.

A missing probability is left missing. The experiment file does not replace it with the filing close rate.
