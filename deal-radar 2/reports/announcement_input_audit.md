# Announcement-date inputs for the M&A put benchmark

This audit covers the 749 verified target filings: role target, not an amendment, and not a same-week duplicate. It reads the stored columns and the saved announcement text. It does not write to the database, and it does not price a put.

The existing benchmark returns a scenario price only when the consideration, the acquisition level, a downside price, the days to the expected close, a close probability, and a pending probability are all present, along with the option contract. A missing input stays missing.

## 1. Already stored and complete

| Field | Stored | Complete among 749 |
| --- | ---: | ---: |
| Announcement date | `announcement_date` | 749 |
| Company identifier | `target_cik` | 749 |
| Company name | `target_name` | 749 |
| Filing URL | `filing_url` | 749 |
| Target ticker | `target_ticker` | 461 |
| Cash offer per share, with the sentence | `offer_price` and `offer_sentence` | 124, of which 122 are labeled cash |
| Consideration | `consideration` | 155: cash 122, stock 31, mixed 2 |
| Exchange ratio | `exchange_ratio` | 33, of which 31 are labeled stock and 2 are labeled mixed |
| Acquirer name | `acquirer_name` | 239 |
| Deal-size sentence | `transaction_value_sentence` | 27 |

Every extracted term on a row shares that row's announcement date. That date is the 8-K filing date. There is no separate column for the date each term became public. `retrieved_at` is the day DealRadar saved the row.

Saved announcement text exists for 728 of the 749 filings, in `data/historical/text`. Twenty-one filings have a URL and no saved text.

## 2. Present in the saved filing text, but not stored

Running the current cash-offer and exchange-ratio readers again on the 728 saved filings adds nothing. Where `offer_price` or `exchange_ratio` is empty, those readers still return empty.

These items are in the saved text and are not columns:

- Expected closing language. The existing close-date reader finds a quarter, half, or month in 38 filings. Thirty-one name a quarter and seven name a month. The reader then assigns the last day of that period. The filing does not print that day. Example, UBOH, filed 2017-03-22: "The Merger is expected to close in the third quarter of 2017."
- A calendar day for the merger itself. A search for "expected to close" plus a month and day finds eight sentences. Six of those sentences are note offerings, not the merger. Two name the merger: accession `0001213900-22-013141`, "the Transactions are expected to close by July 1, 2022," and accession `0001493152-26-018032`, "expected to close on or before April 30, 2026."
- Fixed cash-plus-stock packages that were stored as cash only. CTB, filed 2021-02-24, says each share converts into "$41.75 per share in cash and 0.907 of a share" of Goodyear. The stored row keeps $41.75 and the cash label. Accession `0001193125-19-080078` says each share converts into "$24.63 per share in cash and 0.1505 of a share" of the parent. The ratio reader looks for the words "exchange ratio" followed by a number, so "0.907 of a share" is skipped. One other hit, $76 per share inside an Anadarko award conversion, is not the merger price.
- The two rows already labeled mixed are not a fixed blend the benchmark can add together. STER, filed 2024-03-01, offers an election: "$16.73 per share in cash" or "0.979 shares," subject to proration. The other mixed row, filed 2022-01-10, has no target ticker. Its sentence describes stock consideration and "$3.50 per share in cash."

## 3. Recoverable from other local data, with a narrow use

`historical_deal_outcomes.price_before` is the last stored stock close before the announcement for 237 deals, with `price_before_date`. That close can be a stock price on a date before the announcement. It is not an offer, an exchange ratio, or a downside price.

`historical_stock_prices` can supply an acquirer stock price only when the acquirer ticker is known and a bar exists on the observation date. The three stored `acquirer_ticker` values do not provide that ticker. SUP and CRGY are the target's own cover-page symbol. GIG.RT is a GigCapital right, and the acquirer name is empty on all three rows. There is no local map from the 239 acquirer names to tickers.

Outcome rows exist for all 749 deals. `outcome_date` is filled for 248. That date comes from a later filing. It was not known on the announcement date, so it is not an expected close.

## 4. Cannot be recovered reliably from the announcement

- Downside, the price used if the deal breaks. The word "unaffected" appears in saved text as shares that remain outstanding, not as a break price. No downside column exists.
- Pending probability, and a close probability stated as a number. The outcome row stores filing flags such as HSR and a vote. Those flags are not a probability, and the benchmark does not accept a pending probability from them unless one is supplied.
- A per-share cash offer for the 625 filings with no stored offer. Re-reading the saved text with the current reader does not produce one. A loose search for "per share" also matches par value.
- An exchange ratio for the 716 filings with no stored ratio. Re-reading does not produce one, apart from the share-count wording in section 2, which is not yet a checked ratio.
- Acquirer ticker. The stored values are the registrant's symbol. The announcement head does not add a parent exchange ticker in the form the reader requires.
- The day each term became public, beyond the single 8-K date.
- The 21 filings with no saved text. Their URL is stored. Their wording was not available to re-read.

Of the 124 stored offers, 7 also have a prior close. Five are in a broad range around that close. Two are far from it: the stored offer was left as stored. The other 117 offers have no prior close to compare.

## 5. Would require a source this corpus does not have

- The option contract: strike, expiration, bid, ask, and an implied volatility that is not solved from that same bid and ask.
- The acquirer's stock price on the observation date, after a buyer ticker is identified.
- A downside price, unless a later study defines it from the target's own prior close and labels that definition.
- A pending probability. The announcement does not state one.

## Benchmark-ready deals

A deal is ready only when the announcement, as stored or as re-read here, supplies the consideration, a usable acquisition level, a downside, and an expected close known on the announcement date, without using a later outcome. None do.

| Consideration | Ready for the existing benchmark |
| --- | ---: |
| Cash | 0 |
| Stock | 0 |
| Mixed | 0 |

The 122 stored cash offers, the 31 stored exchange ratios, and the 2 stored mixed rows each lack at least the downside and an expected close stored from the announcement. Stock and mixed rows also lack an acquirer price.
