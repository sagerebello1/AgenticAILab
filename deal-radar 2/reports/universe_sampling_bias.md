# Sampling bias in the acquisition training sample

Generated 2026-11-09. This describes the sample behind the existing XGBoost fit. It is not a new model.

## Companies shared by the training fold and the holdout

The chronological split keeps each CIK in one fold. Measured overlap of priced rows:

- Training and validation companies in both: 0
- Training and holdout companies in both: 0
- Validation and holdout companies in both: 0

Priced rows in those folds: training 502, validation 102, holdout 145. Companies: training 168, validation 56, holdout 57. Earlier deals of a later company are dropped rather than shared: 39 priced rows were excluded that way.

Each company sits in one fold. The companies themselves still come from merger search hits and a small control draw.

## Several snapshots of one acquisition

Every verified deal has three target snapshots, at 30, 90, and 180 days before the announcement. That is 749 deals and 2247 target rows. Among deals that have a stored price, 235 still contribute more than one priced snapshot. In the holdout, 44 deals contribute more than one priced snapshot. Those rows repeat one transaction.

## Positive labels are the offsets

A 30-day positive in this sample is the snapshot placed 30 days before a known announcement. The 90-day positive is the 30-day snapshot or the 90-day snapshot. There is no snapshot 31 to 60 days before the announcement, so the stored 60-day label matches the 30-day label.

## Negative labels are missing phrase matches

Non-acquired snapshots: 126. Of those, 126 are stored with the outcome "no phrase hit for the merger queries in the next 180 days." The phrases are "merge with and into", "merged with and into", and "cash tender offer". 38 of the controls are marked as absent from the current SEC ticker list. None of these rows is a verified statement that no acquisition was announced.

Target CIKs and control CIKs do not overlap (126 controls, drawn only from companies that were not already targets).

## Survivorship

Price requests and results: current_listing_starts_after_historical_date 52, no_bars 3, no_listing 174, ok 284.

Symbols with no Yahoo listing: the historical company is often gone. Symbols whose current listing starts after the historical date were not given that new listing's bars. The 284 stored series are the names Yahoo still charts under the same symbol.

Those series are a window around the sampled event, from 420 days before it through up to 70 days after it. Stored span in calendar days: minimum 70, median 490, maximum 3988. Series shorter than one year: 10 of 284.

## Missing observation windows

- Unread item 1.01 search hits: 8476
- Filings read: 3829 of 25935 search hits
- Search windows whose saved pages are short of the count EDGAR reported: 1581
- SEC submission files on disk: 792. Company-facts files: 252. These are companies already in the deal extract, not a historical constituent list.
- News rows in historical_news_signals: 0
- No CRSP, Compustat, or exchange membership file is stored. WRDS was not logged in.

A representative listed universe, with a price and a complete announcement record on each date, is not on disk.
