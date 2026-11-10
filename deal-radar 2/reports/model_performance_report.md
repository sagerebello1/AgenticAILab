# Model performance

Generated 2026-11-09T18:36Z. No acquisition, price, or closing model was trained.

Not enough point-in-time rows to train. No acquisition probability was produced.

## Acquisition within 30, 90, and 180 days

Usable 30-day rows with a pre-announcement price feature: 8 (4 later announced, 4 did not).

A model needs 100 rows, 20 announcements, 20 non-announcements, and 15 held-out rows. This run has none of the 90-day or 180-day labels, because those windows were not built. Precision, recall, PR-AUC, ROC-AUC, Brier score, and calibration were not calculated.

The abnormal 21-session return is stored in `backtest_results.csv` as a ranking score. It is not a probability.

## Post-announcement price

Deals with both a pre-announcement close and at least one observed post-announcement close: 4. A price model needs 40. Mean absolute error was not calculated, because there is no predicted price.

- GPRO: last close before the filing 1.23, first close on or after the filing 1.69 on 2026-09-02. Offer from the filing: not found. No predicted price.
- ACVA: last close before the filing 7.37, first close on or after the filing 7.22 on 2026-09-10. Offer from the filing: 10.50. No predicted price.
- MG: last close before the filing 19.84, first close on or after the filing 20.75 on 2026-09-18. Offer from the filing: not found. No predicted price.
- CSR: last close before the filing 52.71, first close on or after the filing 57.36 on 2026-09-09. Offer from the filing: not found. No predicted price.

## Deal completion

Labeled announced deals on disk: 18, of which 2 terminated. A closing model needs 40 deals and 8 terminations. The existing `quote.close_probability` values are listed in the CSV. They remain the hand-set 0.90 rule. They were not refit.
