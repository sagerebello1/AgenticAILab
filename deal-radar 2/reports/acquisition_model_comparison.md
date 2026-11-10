# Acquisition model comparison

Generated 2026-11-10T00:34:03Z. The model family was chosen on the validation fold. The holdout numbers below were not used to choose it.

Companies are ordered by their latest announcement date, or by snapshot date when they have no announcement. The earliest 60 percent train, the next 20 percent validate, and the latest 20 percent are the holdout. A company is never in two folds. An earlier deal for a holdout or validation company is dropped, so a 2020 prediction is not scored as part of a later holdout. News columns are left out of these models unless the news section says they were fit.

## 30-day horizon

Training companies 168, validation 56, holdout 56. Training positive rate 0.3127.
Group dates: train 2016-01-08 to 2022-08-01, validation 2022-08-02 to 2024-03-28, holdout 2024-04-01 to 2026-10-13.

| Model | Validation PR-AUC | Validation ROC-AUC | Validation Brier | Holdout PR-AUC | Holdout ROC-AUC | Holdout Brier |
| --- | --- | --- | --- | --- | --- | --- |
| Training base rate | 0.2059 | 0.5000 | 0.1749 | 0.3056 | 0.5000 | 0.2122 |
| XGBoost (depth 2, 160 trees, lambda 1) | 0.4333 | 0.6314 | 0.1550 | 0.5162 | 0.7018 | 0.1903 |
| logistic regression (L2, C=0.1) | 0.3584 | 0.6902 | 0.1658 | 0.3694 | 0.5236 | 0.2198 |
| random forest (depth 5, 200 trees) | 0.3475 | 0.5267 | 0.1694 | 0.4373 | 0.6261 | 0.2022 |

Selected on validation: XGBoost (depth 2, 160 trees, lambda 1).

## 60-day horizon

Not fit. No stored snapshot falls 31 to 60 days before an announcement, so the 60-day label matches the 30-day label on all 786 comparable rows. A separate 60-day probability was not produced.

## 90-day horizon

Training companies 168, validation 56, holdout 56. Training positive rate 0.6255.
Group dates: train 2016-01-08 to 2022-08-01, validation 2022-08-02 to 2024-03-28, holdout 2024-04-01 to 2026-10-13.

| Model | Validation PR-AUC | Validation ROC-AUC | Validation Brier | Holdout PR-AUC | Holdout ROC-AUC | Holdout Brier |
| --- | --- | --- | --- | --- | --- | --- |
| Training base rate | 0.4118 | 0.5000 | 0.2879 | 0.6056 | 0.5000 | 0.2392 |
| XGBoost (depth 2, 160 trees, lambda 1) | 0.7644 | 0.8778 | 0.1488 | 0.7668 | 0.7830 | 0.1754 |
| random forest (depth 5, 200 trees) | 0.7072 | 0.7579 | 0.2382 | 0.7216 | 0.6790 | 0.2193 |
| logistic regression (L2, C=0.1) | 0.6431 | 0.7460 | 0.2206 | 0.7238 | 0.6375 | 0.2331 |

Selected on validation: XGBoost (depth 2, 160 trees, lambda 1).

## News features

The news model was not fit. Training rows with a GDELT observation on the prediction date: 7. The minimum used here is 20. Missing news was not filled with zero, and the price models above do not contain news columns. A with-news versus without-news score is not available.

The announced-deal closing probability and black_scholes.py were not modified.
