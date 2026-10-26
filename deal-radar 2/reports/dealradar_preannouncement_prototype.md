# DealRadar pre-announcement prototype

Run at 2026-10-25T19:51Z. Production scoring code was not edited.

The script finished and produced the scores below. That is a completed technical run. It is not evidence that the score predicts acquisitions. The sample is small, the comparison companies are very large, and the score was not trained.

## Experimental target

Will the company become the target of a publicly announced definitive acquisition agreement or tender offer within the next 30 calendar days?

The prediction timestamp is 00:00 US Eastern on the prediction date. The observation window is the next 30 calendar days, including the 30th day. A filing already public at that timestamp is excluded. Rumors, strategic-review updates, and ordinary contracts are not positive outcomes. A positive outcome requires an 8-K containing "agreement and plan of merger" or an SC TO-T containing "offer to purchase", and the filing company has to be the company being acquired.

For each positive case the prediction date is 30 days before the 8-K filing date, so the filing falls on the last day of the window. Each negative case uses one of those same prediction dates.

## What can be reconstructed

- SEC full-text search accepts a start date and an end date. `edgar.search_filings` ignores that and always ends on today. This experiment calls the same public search with its own dates. It does not change `edgar.search_filings`.
- The registrant CIK and the trading symbol are read from the cached 8-K header. The symbol is an identifier. No other words from the announcement are used as inputs.
- Yahoo's daily chart, through the existing `market.history` function, returns closes for a requested range. Only sessions dated before the prediction date are used. The chart is the one Yahoo returns today, so split adjustments made later can change old levels. It is not a file that was saved on the prediction date.
- Options are not available. `options.CHAIN` records that Yahoo's options endpoint returned HTTP 401. `market.contract` returned: No free options chain is available for CIR. Yahoo's options endpoint returned HTTP 401. Type the bid and ask yourself. A premium will not be filled in.
- Headlines are not available as of a past date. `news.py` says there is no historical headline dataset. Current headlines were not requested, because they can mention an announcement that had not happened yet on the prediction date.
- `features.vectorize` reads the announcement. It was not used.
- `data/model.json` is still absent. No trained model was loaded.

## Scoring method

`experimental/preannouncement.py` computes one number: the stock's return over the 21 trading sessions before the prediction date, minus the SPY return over the same sessions. A larger number means the stock outperformed the market. The formula has no fitted weights. It is an experimental ranking score, not a probability, so there is no calibration table.

`quote.close_probability` was not called. Its 0.90 starting point is the chance an announced deal closes. It was not assigned to these companies.

The baseline gives every company the same score. Its ranking AUC is 0.5 by construction. Training and evaluation are separate because nothing was trained on these outcomes.

## Dataset

Two groups were checked. The first is the 18 June 2023 filings already in the closing-validation cache. Item 1.01 was used only to decide whether the filer was the company being bought. The second is one page of EDGAR 8-Ks from 1 September 2026 through 20 September 2026 that contain "agreement and plan of merger". Amendments filed as 8-K/A were skipped. A filing counts only when Item 1.01 says the filer entered into a new agreement as the company being acquired.

### Scored targets

| Company | Ticker | Prediction | Announcement | 21-day return | SPY return | Score | Last close used |
|---|---|---|---|---|---|---|---|
| GoPro, Inc. | GPRO | 2026-08-03 | 2026-09-02 | +2.6% | +0.2% | 0.0243 | 2026-07-31 |
| ACV Auctions Inc. | ACVA | 2026-08-11 | 2026-09-10 | +8.8% | +2.4% | 0.0645 | 2026-08-10 |
| Mistras Group, Inc. | MG | 2026-08-19 | 2026-09-18 | +18.6% | +3.4% | 0.1515 | 2026-08-18 |
| CENTERSPACE | CSR | 2026-08-10 | 2026-09-09 | +2.7% | +2.9% | -0.0015 | 2026-08-07 |

- GPRO (GoPro, Inc.): 8-K 0001628280-26-060181 filed 2026-09-02. Item 1.01 says the filer entered into an agreement and plan of merger as the company being acquired. No earlier matching filing for CIK 1500435 from 2025-08-03 through 2026-08-03.
- ACVA (ACV Auctions Inc.): 8-K 0000950103-26-013780 filed 2026-09-10. Item 1.01 says the filer entered into an agreement and plan of merger as the company being acquired. No earlier matching filing for CIK 1637873 from 2025-08-11 through 2026-08-11.
- MG (Mistras Group, Inc.): 8-K 0001140361-26-037107 filed 2026-09-18. Item 1.01 says the filer entered into an agreement and plan of merger as the company being acquired. No earlier matching filing for CIK 1436126 from 2025-08-19 through 2026-08-19.
- CSR (CENTERSPACE): 8-K 0001140361-26-035986 filed 2026-09-09. Item 1.01 says the filer entered into an agreement and plan of merger as the company being acquired. No earlier matching filing for CIK 798359 from 2025-08-10 through 2026-08-10.

### Scored companies with no qualifying announcement

| Company | Ticker | Prediction | Window end | 21-day return | SPY return | Score | Last close used |
|---|---|---|---|---|---|---|---|
| Apple Inc. | AAPL | 2026-08-03 | 2026-09-02 | +4.9% | +0.2% | 0.0477 | 2026-07-31 |
| MICROSOFT CORP | MSFT | 2026-08-11 | 2026-09-10 | +31.4% | +2.4% | 0.2902 | 2026-08-10 |
| Alphabet Inc. | GOOGL | 2026-08-19 | 2026-09-18 | -2.2% | +3.4% | -0.0563 | 2026-08-18 |
| JOHNSON & JOHNSON | JNJ | 2026-08-10 | 2026-09-09 | +0.1% | +2.9% | -0.0281 | 2026-08-07 |

- AAPL (Apple Inc.): EDGAR full-text search for CIK 320193 from 2025-08-03 through 2026-09-02 returned no 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase".
- MSFT (MICROSOFT CORP): EDGAR full-text search for CIK 789019 from 2025-08-11 through 2026-09-10 returned no 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase".
- GOOGL (Alphabet Inc.): EDGAR full-text search for CIK 1652044 from 2025-08-19 through 2026-09-18 returned no 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase".
- JNJ (JOHNSON & JOHNSON): EDGAR full-text search for CIK 200406 from 2025-08-10 through 2026-09-09 returned no 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase".

### Not scored

September 2026 page: 67 filings were not a new acquisition of the filer (7 of those are the buyer). They were not scored.

- June 2023: CIRCOR International, Inc. (CIR, target): EDGAR found 8-K 0001140361-23-028228 in the 30 days after 2023-05-06 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for CIR returned HTTP 400. No price was substituted.
- June 2023: Power & Digital Infrastructure Acquisition II Corp. (XPDBU, buyer): The filer is not the company being acquired.
- June 2023: Clover Leaf Capital Corp. (CLOEU, buyer): The filer is not the company being acquired.
- June 2023: Paratek Pharmaceuticals, Inc. (PRTK, target): EDGAR found 8-K 0001193125-23-162024 in the 30 days after 2023-05-08 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for PRTK returned HTTP 404. No price was substituted.
- June 2023: Limeade, Inc. (no symbol, target): The filing cover does not name a trading symbol, so no price was requested.
- June 2023: Nasdaq, Inc. (NDAQ, buyer): The filer is not the company being acquired.
- June 2023: Chinook Therapeutics, Inc. (KDNY, target): EDGAR found 8-K 0001193125-23-164891 in the 30 days after 2023-05-13 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for KDNY returned HTTP 404. No price was substituted.
- June 2023: Gelesis Holdings, Inc. (no symbol, target): The filing cover does not name a trading symbol, so no price was requested.
- June 2023: NexTier Oilfield Solutions Inc. (NEX, target): EDGAR found 8-K 0001193125-23-167339 in the 30 days after 2023-05-16 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for NEX returned HTTP 404. No price was substituted.
- June 2023: Coherus BioSciences, Inc. (CHRS, buyer): The filer is not the company being acquired.
- June 2023: DICE Therapeutics, Inc. (DICE, target): EDGAR found 8-K 0001193125-23-169553 in the 30 days after 2023-05-21 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for DICE returned HTTP 400. No price was substituted.
- June 2023: Quotient Technology Inc. (QUOT, target): EDGAR found 8-K 0001193125-23-170226 in the 30 days after 2023-05-21 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for QUOT returned HTTP 404. No price was substituted.
- June 2023: Talaris Therapeutics, Inc. (TALS, buyer): The filer is not the company being acquired.
- June 2023: Conformis, Inc. (CFMS, target): EDGAR found 8-K 0001305773-23-000032 in the 30 days after 2023-05-24 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for CFMS returned HTTP 404. No price was substituted.
- June 2023: Sigilon Therapeutics, Inc. (SGTX, target): EDGAR found 8-K 0001104659-23-076070 in the 30 days after 2023-05-30 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for SGTX returned HTTP 404. No price was substituted.
- June 2023: Immunome, Inc. (IMNM, buyer): The filer is not the company being acquired.
- June 2023: Kaleyra, Inc. (KLR, target): EDGAR found 8-K 0001193125-23-180610 in the 30 days after 2023-05-31 and no earlier matching filing in the prior 365 days. Yahoo then refused the price history: Yahoo chart for KLR returned HTTP 404. No price was substituted.
- June 2023: TRxADE Health, Inc. (MEDS, buyer): The filer is not the company being acquired.
- September 2026 search reported 275 hits. This run read 71 non-amendment filings from the first page.

## Results

Scored targets: 4. Scored non-targets: 4. Both groups use a 30-day window.

Mean score for targets: 0.0597. Mean score for the other companies: 0.0633.

Ranking AUC of this score on these cases: 0.625. Ranking AUC of the constant baseline: 0.500.

The highest score in this table belongs to a company that did not announce a deal. The average for the targets is lower than the average for the other companies.

These figures describe this handful of cases. 4 targets is too small to establish predictive accuracy. No probability was produced, so Brier score and calibration were not calculated.

## Limitations

- The positive cases are deals already known from a later filing. The prediction date is placed 30 days before that filing. The prices do not include the filing, but the sample is not a screen of the whole market on a random date.
- The comparison names are among the largest listed companies. A score that separates them from small acquisition targets can be a size effect.
- Yahoo's chart for a delisted ticker is incomplete or adjusted after the fact. Cases without a returned history were left unscored.
- An EDGAR search can miss a deal filed by the buyer only, under a different phrase, or on a form this query does not request. The absence of a hit is the evidence recorded above, not a proof that no rumor existed.
- The 21-day abnormal return was chosen as a simple published pattern, not because it won a test. Changing it after seeing these scores would use the same outcomes twice.

## Remaining blockers

There is still no saved record of what a data vendor showed on the prediction morning, no historical option chain, and no historical headline archive. The production EDGAR search still cannot take a historical cutoff. The production app still has no function whose output is the probability of an announcement.

## Smallest next step

Keep this score in the experimental module. Repeat the same 30-day rule on an earlier set of filings, and do not fit anything on the four targets above. A price source that still has delisted tickers is also required before the June 2023 targets can be scored. A fitted probability needs that separate earlier set.
