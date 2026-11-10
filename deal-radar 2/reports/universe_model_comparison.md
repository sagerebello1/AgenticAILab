# Market-wide model comparison

Generated 2026-11-09.

Logistic regression, random forest, and XGBoost were not refit.

The existing XGBoost specification is depth 2, 160 trees, and lambda 1. Its saved experiment file does not contain the trees, and its training labels are the case-control offsets described in `reports/universe_sampling_bias.md`. Scoring that specification on the quarter-end grid would require treating unlabeled company-dates as negatives. That substitution is not made.

The historical acquisition base rate for a listed company over 30 days is not in the stored files. No published base rate was inserted.

Black-Scholes was not changed, and the experiment flag that would pass a probability into the acquisition valuation remains off.
