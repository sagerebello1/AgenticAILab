# DealRadar predictive audit

Generated 2026-11-09T18:36Z. The live close-probability rules were not changed.

## What the app does now

DealRadar scans SEC filings for a merger agreement or a tender offer, reads a cash price from the filing, and prices an option around that announced deal. The chance shown on a deal is the chance the announced deal eventually closes.

`quote.close_probability` starts at 0.90 and moves filing flags in log-odds. With no flags it returns 0.9000. `terms.estimate_probabilities` starts at 0.93, adds the same flags, and clamps the result. `server.build_deal` stores that 0.93-based number unless `data/model.json` exists. That file is absent, so `model.load()` returns nothing.

`training/train.py` can fit a logistic regression and a gradient booster on announcement-filing features, split by date. It has not been run on a collected label file in this project. Its `--demo` path uses synthetic deals and writes `data/model.demo.json`, which the server refuses to load.

The earlier tests on 18 announced deals found that the filing flags do not beat a flat 0.90 close rate by more than noise. The pre-announcement experiment produced a 21-day abnormal-return ranking score for 4 targets and 4 large companies. That score is not a calibrated probability, and its average did not rank the targets above the other companies.

## What is missing

- A point-in-time dataset large enough for a 30-day, 90-day, and 180-day acquisition probability.
- Fundamentals, ownership, historical news, and options history.
- Prices for acquired companies after they leave Yahoo's chart.
- A trained, calibrated closing model with enough terminated deals.
- A model of the traded price after an announcement, as distinct from the offer price.

## What this pass changed

Research code lives in `predictive/` and `scripts/build_predictive_dataset.py`. It writes the dataset report, the performance report, `feature_importance.json`, and `backtest_results.csv`. It saves a model only when the sample gates in `predictive/gates.py` pass. They did not pass, so no probabilities were produced and the company list is unchanged.

The status line on the page says the acquisition model is not trained. The 90% figure on an announced deal is still the closing rule, not the chance a company will be acquired.

## Later phases, in order

1. Keep collecting target and non-target companies with a fixed horizon, and store a price source that still has delisted symbols.
2. Add 90-day and 180-day labels from the same point-in-time rule. Do not multiply the 30-day score.
3. Fit logistic regression first. Compare it with a base rate on a later period. Add a tree model only when that comparison is possible.
4. Build the post-announcement price set until there are at least 40 deals with a pre-close and a post-close.
5. Fit a closing model only after at least 40 announced deals and 8 terminations.
6. Show probabilities on the company list only after a saved model clears those gates.
