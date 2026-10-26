# DealRadar quick validation

Run at 2026-10-25T18:12:01Z. Git c4dd912, Keep a failed data source from wiping the deal list.

**Verdict: TEST BLOCKED — MODEL OR DATA ACCESS ISSUE**

This run executed the existing close-probability rules. It did not produce a valid historical prediction, so no Brier score is reported as evidence of accuracy.

## 1. The probability calculation

DealRadar does not calculate the probability that a merger will be announced. `pClose` is the chance that an already announced deal eventually closes.

Two production functions implement that chance. Neither was modified for this test.

- `quote.close_probability` is the score used by the stock quote and by the on-screen chance before any headline adjustment. It starts at log-odds of **0.90** (`quote.BASE_P`). Each filing flag adds its point adjustment divided by `SCALE = 0.09`, then the result is passed through a logistic function.
- `terms.estimate_probabilities` is the number stored on the deal as `pClose`. It starts at **0.93**, adds the same point adjustments directly, and clamps the result to 0.35–0.98.

The point adjustments, applied only when the filing text sets the flag, are:

| Signal | Points |
|---|---:|
| US antitrust filing (HSR) | -0.01 |
| Second request | -0.10 |
| Each foreign approval, capped at three | -0.03 |
| Each sector approval, capped at two | -0.03 |
| Financing condition | -0.06 |
| Financing explicitly not required | +0.01 |
| Tender offer | +0.02 |
| Shareholder vote, and no tender | -0.01 |
| Go-shop | -0.01 |
| Payment in the buyer's stock | -0.02 |

A call with no flags returns 0.9000 from `quote.close_probability` and 0.930 from `terms.estimate_probabilities`. Those are the announced-deal base rates, not a probability that no deal exists.

`data/model.json` is absent, so no trained model is loaded. The hand-written 0.90 and 0.93 figures are judgments. They are not an announcement frequency measured on a training set. Live Yahoo headlines are not applied here, because a headline fetched today can mention an announcement that has already happened.

Probability source files differ from git HEAD: no.

## 2. The ten companies

Announced deals are companies already in DealRadar for which `workflow.active_quoted` is true: a filing sentence quoted a per-share price, and the filing was not classified as a termination or a completed close. The book source was The running app's GET /api/scan book, scanned at 2026-10-25T17:49:26.883985Z.

Companies without an announced deal were checked with the same EDGAR searches the app uses for one company, over the 120 days ending on the run date. A company is in this group only when both searches returned zero hits. That is evidence about this window, not a claim that the company will never be acquired.

| Company | Ticker | Role | Announcement filing | Outcome | Source |
|---|---|---|---|---:|---|
| Bolt Biotherapeutics, Inc. | BOLT | Announced deal | 2026-10-23 | 1 | 8-K https://www.sec.gov/Archives/edgar/data/1641281/000119312526429647/bolt-20261023.htm filed 2026-10-23. Per-share price quoted from the filing. |
| SMITH & WESSON BRANDS, INC. | SWBI | Announced deal | 2026-10-21 | 1 | 8-K https://www.sec.gov/Archives/edgar/data/1092796/000119312526427316/d166089d8k.htm filed 2026-10-21. Per-share price quoted from the filing. |
| SOUNDTHINKING, INC. | SSTI | Announced deal | 2026-10-20 | 1 | SC TO-T https://www.sec.gov/Archives/edgar/data/1351636/000114036126040176/ny20082824x1_exa1e.htm filed 2026-10-20. Per-share price quoted from the filing. |
| STURM RUGER & CO INC | RGR | Announced deal | 2026-10-20 | 1 | SC TO-T/A https://www.sec.gov/Archives/edgar/data/95029/000119380526001383/e665847_sctota-src.htm filed 2026-10-20. Per-share price quoted from the filing. |
| CCC Intelligent Solutions Holdings Inc. | CCC | Announced deal | 2026-10-15 | 1 | 8-K https://www.sec.gov/Archives/edgar/data/1818201/000119312526422320/d140608d8k.htm filed 2026-10-15. Per-share price quoted from the filing. |
| Apple Inc. | AAPL | No announcement in the search window | None in the search window | 0 | SEC EDGAR full-text search for CIK 320193. No 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase" in the 120 days ending 2026-10-25. |
| MICROSOFT CORP | MSFT | No announcement in the search window | None in the search window | 0 | SEC EDGAR full-text search for CIK 789019. No 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase" in the 120 days ending 2026-10-25. |
| Alphabet Inc. | GOOGL | No announcement in the search window | None in the search window | 0 | SEC EDGAR full-text search for CIK 1652044. No 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase" in the 120 days ending 2026-10-25. |
| JOHNSON & JOHNSON | JNJ | No announcement in the search window | None in the search window | 0 | SEC EDGAR full-text search for CIK 200406. No 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase" in the 120 days ending 2026-10-25. |
| COCA COLA CO | KO | No announcement in the search window | None in the search window | 0 | SEC EDGAR full-text search for CIK 21344. No 8-K containing "agreement and plan of merger" and no SC TO-T containing "offer to purchase" in the 120 days ending 2026-10-25. |

Positive-company notes:

- CCC was not in the current 12-filing scan. The existing company lookup read its filing.

Negative-company checks:

- AAPL (Apple Inc.): 0 merger or tender hit(s) in 120 days.
- MSFT (MICROSOFT CORP): 0 merger or tender hit(s) in 120 days.
- GOOGL (Alphabet Inc.): 0 merger or tender hit(s) in 120 days.
- JNJ (JOHNSON & JOHNSON): 0 merger or tender hit(s) in 120 days.
- KO (COCA COLA CO): 0 merger or tender hit(s) in 120 days.

## 3. What the existing functions returned

The prediction timestamp for every row is the run time, 2026-10-25T18:12:01Z. That is when the functions were called. It is not a date before the announcements.

| Company | Quote probability | Stored additive probability | Filing date | Outcome | Leakage check |
|---|---:|---:|---|---:|---|
| BOLT | 0.8657 | 0.900 | 2026-10-23 | 1 | Failed. The inputs are flags from the announcement filing. |
| SWBI | 0.9000 | 0.930 | 2026-10-21 | 1 | Failed. The inputs are flags from the announcement filing. |
| SSTI | 0.9263 | 0.960 | 2026-10-20 | 1 | Failed. The inputs are flags from the announcement filing. |
| RGR | 0.9183 | 0.950 | 2026-10-20 | 1 | Failed. The inputs are flags from the announcement filing. |
| CCC | 0.8895 | 0.920 | 2026-10-15 | 1 | Failed. The inputs are flags from the announcement filing. |
| AAPL | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |
| MSFT | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |
| GOOGL | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |
| JNJ | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |
| KO | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |

Signal contributions for the announced deals, from `quote.close_probability`:

- **BOLT:** Announced deals close about 9 in 10 times (2.1972); Shareholder vote required (-0.1111); Paid in the acquirer's stock (-0.2222)
- **SWBI:** Announced deals close about 9 in 10 times (2.1972)
- **SSTI:** Announced deals close about 9 in 10 times (2.1972); No financing condition (0.1111); Tender offer (0.2222)
- **RGR:** Announced deals close about 9 in 10 times (2.1972); Tender offer (0.2222)
- **CCC:** Announced deals close about 9 in 10 times (2.1972); US antitrust filing (HSR) (-0.1111); No financing condition (0.1111); Shareholder vote required (-0.1111)

The cash or stock price, the stock price, and the break price are not inputs to either probability function. They are used only later, for the bid and ask.

## 4. Historical-data limits

- No snapshot of these flags was saved before each announcement. The flags were read from the announcement filing on this run.
- No pre-announcement price series was passed into the probability. The function would not use it if one were passed.
- No trained model file and no saved training-set announcement rate are in the repository.
- Companies outside the current scan were read through the existing lookup, which still reads the current filing, not an archived pre-announcement record.
- A zero search result covers 120 days, not the company's whole history.

## 5. Individual Brier scores

Brier score = (predicted probability - outcome)^2. A row is included only when the probability was produced from information available before the outcome.

| Company | Predicted probability | Outcome | Brier score |
|---|---:|---:|---:|
| BOLT | Not a valid pre-outcome prediction | 1 | Not calculated |
| SWBI | Not a valid pre-outcome prediction | 1 | Not calculated |
| SSTI | Not a valid pre-outcome prediction | 1 | Not calculated |
| RGR | Not a valid pre-outcome prediction | 1 | Not calculated |
| CCC | Not a valid pre-outcome prediction | 1 | Not calculated |
| AAPL | Not a valid pre-outcome prediction | 0 | Not calculated |
| MSFT | Not a valid pre-outcome prediction | 0 | Not calculated |
| GOOGL | Not a valid pre-outcome prediction | 0 | Not calculated |
| JNJ | Not a valid pre-outcome prediction | 0 | Not calculated |
| KO | Not a valid pre-outcome prediction | 0 | Not calculated |

Scored announced deals: 5. Valid Brier rows: 0. Unscored non-deal companies: 5. None of the scored rows passed the leakage check, so none entered the average.

## 6. Mean Brier score and baseline

Mean Brier score: **not calculated**. The denominator of valid predictions is 0.

Baseline: **not calculated**. The instruction is to use the announcement frequency in the training data, and not the frequency in these 10 cases. There is no training set loaded. The 0.90 and 0.93 constants are close rates for announced deals, so using either one as an announcement baseline would answer a different question.

## 7. ROC AUC

ROC AUC: **not calculated**. It needs a leakage-free score for at least one announced deal and one company without an announced deal. This run has no leakage-free scores.

The announced deals that were scored sit at 0.8657 to 0.9263 on the quote scale. A call with no flags returns 0.9000. The production path therefore does not give a company a lower probability merely because no announcement was found. It gives that company no probability at all.

## 8. Leakage and other failures

- Every scored probability uses the merger or tender filing. That filing is the announcement, so the input contains the outcome this test would be trying to predict.
- The same transaction is not in a training set, because no training set is loaded. There is also no held-out historical sample.
- Missing pre-announcement inputs are listed above. They were not filled in.
- Non-deal companies stayed in the report with probability "Not scored". They were not dropped and were not assigned 0.90 or 0.93.
- This is a retrospective diagnostic of the current rules. It is not a historical predictive backtest.

## 9. Verdict

**TEST BLOCKED — MODEL OR DATA ACCESS ISSUE**

The existing function ran. A valid test of whether it ranks future announcements did not. The smallest next step is to save, for each company and for a date before its announcement, the inputs the function can actually see. Today those inputs are only filing flags, and the flags do not exist until the announcement filing exists. Until the model has a pre-announcement input, a Brier score against later announcements is not measurable.

