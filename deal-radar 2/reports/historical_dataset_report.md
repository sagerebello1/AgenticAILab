# Historical dataset

Generated 2026-11-09T18:36Z.

## What was collected

- 30-day pre-announcement rows with a cached price feature: 8.
- Announced deals with a close or termination label from the earlier closing test: 18 (2 terminated).
- Still-listed targets with a post-announcement Yahoo close: 4.
- June 2023 symbols asked of Yahoo again: 9. Prices returned: 0.

Rows are in `data/predictive/observations.jsonl`. Each price row names its cache file or the Yahoo error. No missing price was filled in.

## What is missing

- FMP_API_KEY is not set. Financial Modeling Prep was not called, and no fundamentals were filled in.
- POLYGON_API_KEY is not set. Polygon was not called, and no prices were filled in.
- There is no historical headline archive. Today's Yahoo headlines were not requested, because they can mention an announcement that had not happened on the prediction date.
- Yahoo daily chart via market.history. Delayed bars. Delisted symbols often return HTTP 400 or 404.
- SEC EDGAR full-text search can take a historical start and end. Production search_filings still ends on today.
- Options chains are unavailable. Yahoo's options endpoint returned HTTP 401 and is not bypassed.
- yfinance is not used. It is not installed, and it is not a way around the options refusal.
- Revenue, EBITDA, market cap, enterprise value, debt, cash, price-to-earnings, price-to-sales, and institutional ownership. No point-in-time fundamentals source is connected.
- Acquirer identity is in some filing texts and was not turned into a learned acquirer model.
- Deal value, regulatory flags, and consideration are parsed only for the 18 cached closing-test filings, and only as announcement-time fields.
- 90-day and 180-day acquisition labels.
- A survivorship-safe set of delisted companies. Yahoo did not return their charts.

## June 2023 price check

- CIR, announcement 2023-06-05: Yahoo chart for CIR returned HTTP 400. No price was substituted.
- PRTK, announcement 2023-06-07: Yahoo chart for PRTK returned HTTP 404. No price was substituted.
- KDNY, announcement 2023-06-12: Yahoo chart for KDNY returned HTTP 404. No price was substituted.
- NEX, announcement 2023-06-15: Yahoo chart for NEX returned HTTP 404. No price was substituted.
- DICE, announcement 2023-06-20: Yahoo chart for DICE returned HTTP 400. No price was substituted.
- QUOT, announcement 2023-06-20: Yahoo chart for QUOT returned HTTP 404. No price was substituted.
- CFMS, announcement 2023-06-23: Yahoo chart for CFMS returned HTTP 404. No price was substituted.
- SGTX, announcement 2023-06-29: Yahoo chart for SGTX returned HTTP 404. No price was substituted.
- KLR, announcement 2023-06-30: Yahoo chart for KLR returned HTTP 404. No price was substituted.

## Look-ahead rule

The 30-day features use only chart dates before the prediction date. The announcement filing is the label, not a feature. Closing-model flags come from the announcement, so they are excluded from the pre-announcement rows. Post-announcement prices are outcomes for a price study, and they are not copied into the pre-announcement features.
