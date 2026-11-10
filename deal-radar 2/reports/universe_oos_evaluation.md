# Chronological out-of-sample evaluation

Generated 2026-11-09.

A market-wide holdout was not scored. The eligible universe has zero verified negatives, so precision and recall among the highest-ranked names would not be a test of acquisition prediction.

| Measure | Result |
| --- | --- |
| PR-AUC | not computed |
| ROC-AUC | not computed |
| Brier score | not computed |
| Calibration curve | not computed |
| Precision@10 | not computed |
| Precision@20 | not computed |
| Recall@10 | not computed |
| Recall@20 | not computed |
| Lift over the market-wide 30-day base rate | not computed |

The market-wide base rate is missing for the same reason as the negatives: the listed population and the complete announcement record are not stored. The earlier case-control holdout, where about 30 percent of rows were pre-built 30-day offsets, is not this base rate and is not repeated here as predictive accuracy.

The results were not connected to Black-Scholes.
