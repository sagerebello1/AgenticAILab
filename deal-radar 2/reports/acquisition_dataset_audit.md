# Historical acquisition dataset audit

Generated 2026-11-10T00:34:03Z, before the model fit. No live probability was changed.

## What is on disk

- SEC search hits: 25935
- Verified target transactions: 749
- Verified transactions missing a target ticker: 288
- Unread item 1.01 hits: 8476
- Company snapshots: 2373
- Distinct companies in the snapshots: 791
- Target snapshots: 2247
- Non-acquired snapshots: 126
- Stored Yahoo bars: 105205 across 284 tickers
- Price field used for returns: adj_close
- Adjusted closes stored: 105205
- Rows in historical_news_signals: 0
- GDELT pilot feature rows: 17
- Market series: S&P 500 ETF daily closes, used only as the market return. Retrieved 2026-11-10T00:31:11Z.

## Snapshot dates

- Earliest snapshot: 2015-07-09
- Latest snapshot: 2026-09-13
- Announcement span: 2016-01-05 to 2026-10-13
- Target snapshot offsets: 30 days (749 rows), 90 days (749 rows), 180 days (749 rows)

## Rows that can be modeled

A row is modeled only when it has a ticker and a price bar on or before the snapshot. A missing ticker is not used as a feature, because missing tickers are more common where the filing parser failed.

- No CIK: 0
- No ticker: 881
- Ticker with no stored bars: 692
- Bars only after the snapshot: 12
- Price known on the snapshot: 788

30-day labels among priced rows: 235 positives, 552 negatives, 1 censored.
60-day labels among priced rows: 234 positives, 552 negatives, 2 censored.
90-day labels among priced rows: 468 positives, 317 negatives, 3 censored.

## Feature coverage on priced 30-day rows

- 30-day return: 787 of 787 modeling rows
- 90-day return: 784 of 787 modeling rows
- 30-day abnormal return: 787 of 787 modeling rows
- 30-day volume change: 780 of 787 modeling rows
- 30-session volatility: 787 of 787 modeling rows
- log market cap: 314 of 787 modeling rows
- log assets: 325 of 787 modeling rows
- observed news: 8 of 787 modeling rows

GDELT observations attached to a priced row: 8. A day with no matched article is an explicit zero. A company that was not in the pilot is missing, not zero. Rolling 7, 30, and 90 day news changes are missing for every row because the pilot archive is one UTC day.

## Data-quality limits

- Target snapshots are the announcement date minus 30, 90, and 180 days. A 30-day positive is that 30-day offset.
- A non-acquired label means three EDGAR phrases returned no hit in the horizon. It does not prove the company was never acquired.
- Unread item 1.01 hits: 8476. Verified transactions: 749. The acquired set is the portion of the search that was read.
- Distinct non-acquired companies: 126.
- Repeated snapshots of one deal are not independent companies.
- Yahoo closes are unadjusted except where the stored adjusted close was complete. Delisted symbols are missing when Yahoo has no series.
- GDELT pilot feature rows: 17.
- historical_news_signals has 0 rows.
- S&P 500 ETF daily closes, used only as the market return. Retrieved 2026-11-10T00:31:11Z.

## Look-ahead check

- Stored last-close dates after the snapshot: 0
- Stored financial filed dates after the snapshot: 0
- Features that changed when later price bars were removed: 0 of 788 priced rows
- Market-wide sample: no
- Acquired companies were sampled at fixed offsets before a known announcement, so the 30-day label is the sampling design. Unread item 1.01 hits (8476) exceed verified transactions (749). Non-acquired labels come from an EDGAR phrase screen, not from a census of companies that stayed independent.
