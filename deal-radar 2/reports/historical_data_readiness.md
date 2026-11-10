# Historical data readiness

Generated 2026-11-09T21:21:33Z. No model was trained in this run.

## Counts

- Search hits stored: 25935
- Filings read: 3829
- Verified target transactions, after dropping amendments and same-week duplicates: 749
- Buyer filings read and excluded from that count: 620
- Unclear or not a merger after reading: 2414
- Competing-offer links: 38
- Closed, from a later filing sentence: 234
- Terminated, from a later filing sentence: 14
- Unresolved transactions: 501
- Non-acquired company snapshots: 126
- Tickers with at least one stored price bar: 284 of 513 requested
- Usable 30-day observations: 2298 (positives 728, negatives 1570)
- Usable 90-day observations: 2293 (positives 1452, negatives 841)
- Usable 180-day observations: 2279 (positives 2167, negatives 112)
- Verified deals with a pre-announcement close and a later market close: 237
- Market close one session before announcement: 237
- Market close on the announcement session: 238
- Market close one session after: 238
- Market close five sessions after: 238
- Market close ten sessions after: 238
- Market close thirty sessions after: 237
- Observed premium, only where both the cash offer and the pre-close exist: 7
- News rows: 0
- Look-ahead violations: 0

## Missing fields among verified transactions

- target_ticker: 288
- acquirer_name: 510
- acquirer_ticker: 746
- consideration: 594
- offer_price: 625
- exchange_ratio: 716
- transaction_value: 723
- outcome: 501

## Provider limits

- FMP_API_KEY is not set. Financial Modeling Prep was not called.
- POLYGON_API_KEY is not set. Polygon was not called.
- Stooq probe returned HTTP 200 and was blocked. No Stooq prices were stored.
- CIRCOR window: Yahoo HTTP 400 (Data doesn't exist for startDate = 1682899200, endDate = 1686096000). Current listing Corgi CRCL 2x Daily ETF, first trade 2026-07-07. Those recent bars were not stored as the old company's history.
- Paratek window: Yahoo HTTP 404 (No data found, symbol may be delisted). Current listing unnamed, first trade unknown. Those recent bars were not stored as the old company's history.
- On a 2023 first-quarter check, EDGAR full-text pages from=0 and from=100 shared 15 of 100 accessions. Hits are deduplicated by accession. A page overlap can also skip a filing, so the search list is not a complete census.
- No historical news archive is connected. historical_news_signals was not filled.
- Financial statements are taken from SEC companyfacts only when the fact's filed date is on or before the snapshot.
- Unread item 1.01 search hits remaining: 8476.
- Search windows whose saved hits are below the count EDGAR reported: 1581.
- Repeated companies are not independent observations. Distinct non-acquired companies: 126.
- A control label of zero means the three EDGAR phrases returned no hit. It does not prove the company was never acquired.
- Target snapshots are dated from a known announcement. They are case-control rows, not a random draw of the market.
- Production close probabilities were not changed, and no model file was written by this script.

## Ready for a later training run

- acquisition: no
- post_announcement_price: no
- deal_completion: no
- A model was trained: no

## Why a row count is not completeness

- Most item 1.01 search hits were not read. The transaction list is a sample, not the full set of filings.
- The 30, 90, and 180 day rows repeat the same announced deals. They are not separate companies.
- 237 deals have a market close before and after the announcement. Only 7 also have a cash offer, so an offer-to-market comparison is not supported yet.
- 248 deals have a closing or termination sentence. 501 do not, so the outcome label is missing for most transactions.
