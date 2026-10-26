# DealRadar closing-probability validation

Run at 2026-10-25T18:43Z. Git c4dd912, Keep a failed data source from wiping the deal list.

**These results are preliminary.** The evaluation sample, the separate training sample, or the number of terminated deals is smaller than a stable test needs.

Production files differing from git HEAD: workflow.py.

`quote.close_probability` was called unchanged. No probability rule was edited for this test.

## 1. Formula and inputs

`quote.close_probability` estimates the chance that an already announced deal eventually closes. The docstring in `quote.py` calls this the filing chance and sets the starting point at nine in ten announced deals. It does not estimate whether a deal will be announced, and it does not use the stock price.

The executed formula is:

```
points = sum of the filing adjustments below
close = sigmoid(logit(0.90) + points / 0.09)
```

`BASE_P` is 0.90. `SCALE` is 0.09, which is 0.90 times 0.10. One adjustment point therefore moves the log-odds by 1/0.09. The logistic function turns that sum back into a probability. A call with no flags returns 0.9000.

The same call also returns a legacy additive score, starting at 0.93 and clamped to 0.35–0.98. The number used in this test is the logistic `close` value, which is the score `quote.respond` uses when the caller does not override it.

Adjustments, confirmed by calling the function once per flag:

| Input present in the announcement filing | Probability |
|---|---|
| No filing flags | 0.9000 |
| HSR | 0.8895 |
| Second request | 0.7476 |
| One foreign approval | 0.8657 |
| One sector approval | 0.8657 |
| Financing condition | 0.8221 |
| Financing explicitly not required | 0.9096 |
| Tender offer | 0.9183 |
| Shareholder vote, no tender | 0.8895 |
| Go-shop | 0.8895 |
| Stock consideration | 0.8781 |

The point schedule inside the function is HSR -0.01, second request -0.10, each foreign regulator -0.03 (capped at -0.09), each sector regulator -0.03 (capped at -0.06), financing condition -0.06, financing explicitly absent +0.01, tender +0.02, shareholder vote without a tender -0.01, go-shop -0.01, and stock consideration -0.02.

Inputs available at announcement are the words in that announcement's 8-K packet. This test reads them the same way the server does: the primary document, then a press release or exhibit only until a per-share price is found. Later closing filings and termination filings are not included in that packet.

A flag is true when `terms.extract_terms` finds its phrase. "Second request" matches the words anywhere in that packet, including a condition in the agreement that describes a second request which has not been issued. That is how the current function behaves. This test does not correct it.

## 2. Transactions and verified outcomes

Announcements were SEC 8-K filings that report Item 1.01 and contain "agreement and plan of merger". A deal is verified only when a later filing, within 540 days, states that the merger or business combination closed, or states that the merger agreement was terminated. The outcome sentence had to come from the 8-K or a press release, not from a copy of the merger agreement. Deals without that sentence stayed out of the scores.

Training window for the baseline: 2022-01-03 through 2022-06-30. Filings examined: 120. Kept for the close rate: 34 (33 closed, 1 terminated). Unresolved or unconfirmed: 49. Not an original signing: 31. Outcome within 7 days: 2. Submission errors: 0. Duplicate filings removed: 4.

Evaluation window: 2023-06-01 through 2024-03-31. The search stopped once 20 original signing filings with a confirmed later outcome were found, or the window ended. Filings examined: 58. Original signings before duplicate removal: 20. Unresolved or unconfirmed: 26. Not an original signing: 12. Outcome within 7 days: 0. Submission errors: 0.

### Evaluation deals

| Filer | Ticker | Announced | Outcome | Outcome date | Evidence from the outcome filing |
|---|---|---|---|---|---|
| CIRCOR INTERNATIONAL INC | — | 2023-06-05 | Closed | 2023-10-18 | m 1.01 Entry into a Material Definitive Agreement. Credit Agreement Concurrently with the closing of the Merger, Cube Intermediate 2 LLC, Delaware limited liability company (“ Intermediate ”), Cube Par |
| AirJoule Technologies Corp. | AIRJ | 2023-06-05 | Closed | 2024-03-20 | tatement/Prospectus. Pursuant to the terms and subject to the conditions set forth in the Merger Agreement, the Business Combination was consummated on March 14, 2024 (the “Closing”). Item 2.01 of this Report discusses the consummation of |
| Clover Leaf Capital Corp. | CLOE | 2023-06-06 | Terminated | 2024-11-08 | ay that Clover Leaf and Kustom Entertainment, Inc. (“Kustom Entertainment”) have mutually agreed to terminate their previously announced Agreement and Plan of Merger (the “Merger Agreement”), effective as of November 7, 2024 by entering into a mutual term |
| Paratek Pharmaceuticals, Inc. | — | 2023-06-07 | Closed | 2023-09-21 | er of Merger Sub with and into the Company (the “Merger”), with the Company surviving the Merger as a wholly-owned subsidiary of Parent. On September 21, 2023, the Company completed the Merger. Pursuant to the Merger Agreement, at the effective time of the Merger (the “E |
| LIMEADE, INC | — | 2023-06-09 | Closed | 2023-08-09 | port on Form 8-K is incorporated by reference into this Item 1.02. In connection with the consummation of the Merger, on August 9, 2023, the Company repaid in full all outstanding amounts under the Amended |
| NASDAQ, INC. | NDAQ | 2023-06-12 | Closed | 2023-11-03 | unds managed by Thoma Bravo, L.P., a Delaware limited partnership (“Thoma Bravo”). At the effective time of the Mergers, Nasdaq delivered to Seller (i) an aggregate of 85,608,414 newly issued shares of common |
| CHINOOK THERAPEUTICS, INC. | — | 2023-06-12 | Closed | 2023-08-11 | er Sub Inc., a Delaware corporation and an indirect wholly owned subsidiary of Novartis (“Merger Sub”). As previously disclosed, on August 2, 2023, at a special meeting of stockholders of the Company, the Company’s st |
| GELESIS HOLDINGS, INC. | GLSHQ | 2023-06-13 | Terminated | 2023-10-16 | ger, the Parent delivered to the Company a written notice of termination, terminating the Merger Agreement pursuant to the terms thereof. As a result of the termination of the Merger Agreement, the Voting and Support Agreement, dated as of June 12, 2023, by and between the Compan |
| NEXTIER OILFIELD SOLUTIONS INC. | — | 2023-06-15 | Closed | 2023-09-01 | nge Act. Item 1.02 Termination of a Material Definitive Agreement. In connection with the consummation of the Mergers (as defined below), on September 1, 2023, NexTier Oilfield Solutions Inc. (the “Company” |
| PATTERSON UTI ENERGY INC | PTEN | 2023-06-15 | Closed | 2023-08-14 | iving entity (such merger, together with the First Company Merger, the “ Mergers ”). Upon consummation of the Mergers and the other transactions contemplated by the Merger Agreement (the “ Transactions ”) o |
| Coherus Oncology, Inc. | CHRS | 2023-06-16 | Closed | 2023-09-08 | iving Entity ”). The Mergers became effective on September 8, 2023 upon the filing of the Certificate of Merger for the First Merger with the Secretary of the State of Delaware (the time of the filing |
| Surface Oncology, Inc. | — | 2023-06-16 | Closed | 2023-09-08 | iving Entity ”). The Mergers became effective on September 8, 2023 upon the filing of the Certificate of Merger for the First Merger with the Secretary of the State of Delaware (the time of the filing |
| DICE Therapeutics, Inc. | — | 2023-06-20 | Closed | 2023-08-09 | olly-owned subsidiary of Parent. Pursuant to the terms of the Merger Agreement, as of the effective time of the Merger (the “ Effective Time ”), by virtue of the Merger and without any action on the part of t |
| Quotient Technology Inc. | — | 2023-06-20 | Closed | 2023-09-05 | eport on Form 8-K is incorporated by reference into this Item 1.01. Concurrently with the closing of the Merger, CB Neptune Midco Holdings, LLC (“ CB Neptune Midco ”), Parent and each of Parent’s direc |
| Tourmaline Bio, Inc. | TRML | 2023-06-22 | Closed | 2023-10-20 | October 19, 2023, the Delaware corporation formerly known as “Talaris Therapeutics, Inc.” completed its previously announced merger transaction in accordance with the terms of the Agreement and Plan of Merger, dated as of |
| Conformis Inc | — | 2023-06-23 | Closed | 2023-09-05 | is Current Report on Form 8-K is incorporated herein by reference. In connection with the consummation of the Merger, on September 5, 2023, the Company repaid in full all outstanding indebtedness and termin |
| Sigilon Therapeutics, Inc. | — | 2023-06-29 | Closed | 2023-08-11 | 23, following consummation of the Offer, Purchaser merged with and into the Company (the “Merger”), with the Company as the surviving corporation. The Merger was completed pursuant to Section 251(h) of the General Corporation Law of the State of Delaware (the “ |
| Immunome Inc. | IMNM | 2023-06-29 | Closed | 2023-10-04 | ) of the Exchange Act. ¨ Explanatory Note On October 2, 2023, Immunome, Inc. (“Immunome”) completed its previously announced merger transaction in accordance with the terms and conditions of the Agreement and Plan of Merg |
| Kaleyra, Inc. | — | 2023-06-30 | Closed | 2023-10-10 | logies Inc., a Delaware corporation and wholly owned subsidiary of Tata Communications (“ Merger Sub ”), completed the transactions contemplated by that certain Agreement and Plan of Merger, dated as of J |
| Scienture Holdings, Inc. | MEDS | 2023-06-30 | Closed | 2023-07-31 | Section 13(a) of the Exchange Act. ☐ Item 1.01 Entry into a Material Definitive Agreement Completion of Merger As previously disclosed, on July 14, 2023, TRxADE HEALTH, Inc., a Delaware corporation (t |

### Training deals used only for the close rate

These deals fix the baseline probability. Their outcomes are not in the evaluation average.

| Filer | Ticker | Announced | Outcome | Outcome date |
|---|---|---|---|---|
| Distribution Solutions Group, Inc. | DSGR | 2022-01-04 | Closed | 2022-04-04 |
| CASTLIGHT HEALTH, INC. | — | 2022-01-05 | Closed | 2022-02-17 |
| VOCERA COMMUNICATIONS, INC. | — | 2022-01-06 | Closed | 2022-02-23 |
| Alteryx, Inc. | — | 2022-01-07 | Closed | 2022-02-08 |
| ACCENDRA HEALTH INC/VA/ | OMI | 2022-01-10 | Closed | 2022-03-29 |
| Apria, Inc. | — | 2022-01-10 | Closed | 2022-03-29 |
| ZYNGA INC | — | 2022-01-10 | Closed | 2022-05-23 |
| CIVISTA BANCSHARES, INC. | CIVB | 2022-01-10 | Closed | 2022-07-01 |
| STR Sub Inc. | — | 2022-01-12 | Closed | 2022-12-29 |
| Poema Global Holdings Corp. | — | 2022-01-18 | Closed | 2022-04-04 |
| GeneDx Holdings Corp. | WGS | 2022-01-18 | Closed | 2022-05-02 |
| Sorrento Therapeutics, Inc. | SRNE | 2022-01-19 | Closed | 2022-02-01 |
| ZOGENIX, INC. | — | 2022-01-19 | Closed | 2022-03-07 |
| Resource REIT, Inc. | — | 2022-01-24 | Closed | 2022-05-19 |
| Akili, Inc. | — | 2022-01-26 | Closed | 2022-08-23 |
| Live Current Media Inc. | — | 2022-01-27 | Closed | 2022-04-28 |
| CITRIX SYSTEMS INC | — | 2022-01-31 | Closed | 2022-10-03 |
| SOC Telemed, Inc. | — | 2022-02-04 | Closed | 2022-04-06 |
| Vivani Medical, Inc. | VANI | 2022-02-08 | Closed | 2022-09-02 |
| US Ecology, Inc. | — | 2022-02-10 | Closed | 2022-05-02 |
| Signify Health, Inc. | — | 2022-02-10 | Closed | 2023-03-29 |
| BIODELIVERY SCIENCES INTERNATIONAL INC | — | 2022-02-14 | Closed | 2022-03-22 |
| Resonant Inc | — | 2022-02-14 | Closed | 2022-03-28 |
| Nogin, Inc. | — | 2022-02-14 | Closed | 2022-09-01 |
| MASIMO CORP | MASI | 2022-02-15 | Closed | 2022-04-12 |
| MONEYGRAM INTERNATIONAL INC | — | 2022-02-15 | Closed | 2023-06-01 |
| Equillium, Inc. | EQ | 2022-02-16 | Terminated | 2022-12-23 |
| PREFERRED APARTMENT COMMUNITIES INC | — | 2022-02-16 | Closed | 2022-06-23 |
| Houghton Mifflin Harcourt Co | — | 2022-02-22 | Closed | 2022-04-07 |
| MERITOR, INC. | — | 2022-02-22 | Closed | 2022-08-03 |
| TENNECO INC | — | 2022-02-23 | Closed | 2022-11-17 |
| SOUTH JERSEY INDUSTRIES INC | — | 2022-02-24 | Closed | 2023-02-01 |
| Origin Bancorp, Inc. | OBK | 2022-02-24 | Closed | 2022-08-01 |
| CORPORATE PROPERTY ASSOCIATES 18 GLOBAL INC | — | 2022-02-28 | Closed | 2022-08-04 |

## 3. Predicted probabilities

Each probability is `quote.close_probability` on flags from that deal's announcement packet. The call was made on this run. The prediction date for the information used is the announcement filing date, not the run date.

| Ticker | Announced | Flags from the announcement | Predicted close probability | Outcome |
|---|---|---|---|---|
| — | 2023-06-05 | HSR, vote, cash | 0.8781 | 1 |
| AIRJ | 2023-06-05 | HSR, vote | 0.8781 | 1 |
| CLOE | 2023-06-06 | vote, cash | 0.8895 | 0 |
| — | 2023-06-07 | HSR, vote, cash | 0.8781 | 1 |
| — | 2023-06-09 | vote, cash | 0.8895 | 1 |
| NDAQ | 2023-06-12 | HSR, vote, cash | 0.8781 | 1 |
| — | 2023-06-12 | HSR, no financing condition, vote, cash | 0.8895 | 1 |
| GLSHQ | 2023-06-13 | no financing condition, vote, go-shop, cash | 0.8895 | 0 |
| — | 2023-06-15 | HSR, tender, mixed | 0.9096 | 1 |
| CHRS | 2023-06-16 | vote, mixed | 0.8895 | 1 |
| — | 2023-06-20 | HSR, no financing condition, tender, cash | 0.9183 | 1 |
| — | 2023-06-20 | HSR, no financing condition, cash | 0.9000 | 1 |
| TRML | 2023-06-22 | no financing condition, tender, mixed | 0.9263 | 1 |
| — | 2023-06-23 | vote, cash | 0.8895 | 1 |
| — | 2023-06-29 | no financing condition, tender, cash | 0.9263 | 1 |
| IMNM | 2023-06-29 | vote, mixed | 0.8895 | 1 |
| — | 2023-06-30 | HSR, vote, cash | 0.8781 | 1 |
| MEDS | 2023-06-30 | HSR, sector: FCC, no financing condition, tender, cash | 0.8895 | 1 |

Predicted probabilities ranged from 0.8781 to 0.9263. The mean prediction was 0.8937.

Mean prediction on deals that closed: 0.8943 (n=16).
Mean prediction on deals that were terminated: 0.8895 (n=2).

## 4. Brier scores

Brier score = (predicted probability − outcome)². Closed is 1 and terminated is 0. Lower is better.

| Ticker | Predicted | Outcome | Brier |
|---|---|---|---|
| — | 0.8781 | 1 | 0.0148 |
| AIRJ | 0.8781 | 1 | 0.0148 |
| CLOE | 0.8895 | 0 | 0.7913 |
| — | 0.8781 | 1 | 0.0148 |
| — | 0.8895 | 1 | 0.0122 |
| NDAQ | 0.8781 | 1 | 0.0148 |
| — | 0.8895 | 1 | 0.0122 |
| GLSHQ | 0.8895 | 0 | 0.7913 |
| — | 0.9096 | 1 | 0.0082 |
| CHRS | 0.8895 | 1 | 0.0122 |
| — | 0.9183 | 1 | 0.0067 |
| — | 0.9000 | 1 | 0.0100 |
| TRML | 0.9263 | 1 | 0.0054 |
| — | 0.8895 | 1 | 0.0122 |
| — | 0.9263 | 1 | 0.0054 |
| IMNM | 0.8895 | 1 | 0.0122 |
| — | 0.8781 | 1 | 0.0148 |
| MEDS | 0.8895 | 1 | 0.0122 |

Valid transactions: 18.
Closed: 16 of 18 (88.9%).
Mean predicted probability: 0.8937.
Mean Brier score: 0.0981.
Mean Brier on closed deals: 0.0114.
Mean Brier on terminated deals: 0.7913.
ROC AUC: 0.500. This ranks closed deals against terminated deals. With 2 terminated deals, the rank is unstable.

## 5. Baseline comparison

The baseline predicts 0.9706 for every evaluation deal. That is the share of verified training deals that closed: 33 of 34, announced from 2022-01-04 through 2022-02-28. It was not computed from the evaluation outcomes.

Baseline Brier score on the same evaluation deals: 0.1054.
DealRadar mean Brier score: 0.0981.
Difference (baseline minus DealRadar): 0.0073. A positive difference means the filing flags beat a constant prediction at the training close rate.
A 2,000-draw bootstrap of the evaluation deals, with the training rate held fixed, put that difference between -0.0113 and 0.0339 (2.5th to 97.5th percentile).

The training rate is the rate among deals whose outcome filing could be confirmed. Deals that never filed a clear closing or termination notice are not in it. It is not the close rate of every announced merger.

## 6. Missing inputs, leakage, and other limits

- Outcome text was not fed into `quote.close_probability`.
- The training deals and the evaluation deals come from different months. An evaluation company whose CIK already appeared in the training set was skipped.
- 49 examined training filings and 26 examined evaluation filings had no confirmed outcome and were left out. They were not labeled as closed.
- Amendment filings, and filings that do not say the company entered into a merger agreement, were left out. A later amendment can contain terms that were not in the original announcement.
- An outcome dated less than 7 days after the filing was left out. Those filings were often describing a closing that was already underway.
- Scored-set exclusions:
  - PTEN (2023-06-15): Same transaction as NEXTIER OILFIELD SOLUTIONS INC., filed 2023-06-15.
  - Surface Oncology, Inc. (2023-06-16): Same transaction as CHRS, filed 2023-06-16.
- Second-request flag was set on 0 scored deals. At announcement this phrase is often a condition written into the agreement, not a request the regulator has already made.
- Buyer and target can each file an 8-K for one deal. A later filing that named a party from an earlier filing in the same two-week span was removed from the scored set when the name match was clear.
- The extractor can miss a flag that is present, or set one from a boilerplate phrase. Scores use the extractor's reading.
- No `data/model.json` file was used. This test does not load or change a trained model.
- Uncommitted edits exist in workflow.py. quote.py is not one of them.

### Sources

- CIRCOR INTERNATIONAL INC, announced 2023-06-05. Announcement: https://www.sec.gov/Archives/edgar/data/1091883/000114036123028228/brhc20054011_8k.htm. Outcome filing 8-K 2023-10-18: https://www.sec.gov/Archives/edgar/data/1091883/000114036123048598/ef20012725_8k.htm.
- AIRJ, announced 2023-06-05. Announcement: https://www.sec.gov/Archives/edgar/data/1855474/000121390023045982/ea179769-8k425_power2.htm. Outcome filing 8-K 2024-03-20: https://www.sec.gov/Archives/edgar/data/1855474/000121390024024441/ea0202160-8k_montana.htm.
- CLOE, announced 2023-06-06. Announcement: https://www.sec.gov/Archives/edgar/data/1849058/000121390023046531/ea179755-8k425_clover.htm. Outcome filing 8-K 2024-11-08: https://www.sec.gov/Archives/edgar/data/1849058/000121390024095625/ea0220446-8k_clover.htm.
- Paratek Pharmaceuticals, Inc., announced 2023-06-07. Announcement: https://www.sec.gov/Archives/edgar/data/1178711/000119312523162024/d407022d8k.htm. Outcome filing 8-K 2023-09-21: https://www.sec.gov/Archives/edgar/data/1178711/000119312523239185/d524523d8k.htm.
- LIMEADE, INC, announced 2023-06-09. Announcement: https://www.sec.gov/Archives/edgar/data/1381507/000138150723000027/lme-20230608.htm. Outcome filing 8-K 2023-08-09: https://www.sec.gov/Archives/edgar/data/1381507/000138150723000044/lme-20230809.htm.
- NDAQ, announced 2023-06-12. Announcement: https://www.sec.gov/Archives/edgar/data/1120193/000119312523164839/d476077d8k.htm. Outcome filing 8-K 2023-11-03: https://www.sec.gov/Archives/edgar/data/1120193/000119312523270374/d655352d8k.htm.
- CHINOOK THERAPEUTICS, INC., announced 2023-06-12. Announcement: https://www.sec.gov/Archives/edgar/data/1435049/000119312523164891/d511815d8k.htm. Outcome filing 8-K 2023-08-11: https://www.sec.gov/Archives/edgar/data/1435049/000119312523210803/d103891d8k.htm.
- GLSHQ, announced 2023-06-13. Announcement: https://www.sec.gov/Archives/edgar/data/1805087/000095017023027586/gls-20230612.htm. Outcome filing 8-K 2023-10-16: https://www.sec.gov/Archives/edgar/data/1805087/000095017023053536/gls-20231012.htm.
- NEXTIER OILFIELD SOLUTIONS INC., announced 2023-06-15. Announcement: https://www.sec.gov/Archives/edgar/data/1688476/000119312523167339/d461451d8k.htm. Outcome filing 8-K 2023-09-01: https://www.sec.gov/Archives/edgar/data/1688476/000168847623000147/frac-20230901.htm.
- PTEN, announced 2023-06-15. Announcement: https://www.sec.gov/Archives/edgar/data/889900/000119312523167408/d494894d8k.htm. Outcome filing 8-K 2023-08-14: https://www.sec.gov/Archives/edgar/data/889900/000095017023042391/pten-20230814.htm.
- CHRS, announced 2023-06-16. Announcement: https://www.sec.gov/Archives/edgar/data/1512762/000119312523168448/d523169d8k.htm. Outcome filing 8-K 2023-09-08: https://www.sec.gov/Archives/edgar/data/1512762/000155837023015582/chrs-20230908x8k.htm.
- Surface Oncology, Inc., announced 2023-06-16. Announcement: https://www.sec.gov/Archives/edgar/data/1718108/000119312523168488/d497538d8k.htm. Outcome filing 8-K 2023-09-08: https://www.sec.gov/Archives/edgar/data/1718108/000119312523231197/d525254d8k.htm.
- DICE Therapeutics, Inc., announced 2023-06-20. Announcement: https://www.sec.gov/Archives/edgar/data/1645569/000119312523169553/d521514d8k.htm. Outcome filing 8-K 2023-08-09: https://www.sec.gov/Archives/edgar/data/1645569/000119312523206894/d502246d8k.htm.
- Quotient Technology Inc., announced 2023-06-20. Announcement: https://www.sec.gov/Archives/edgar/data/1115128/000119312523170226/d473281d8k.htm. Outcome filing 8-K 2023-09-05: https://www.sec.gov/Archives/edgar/data/1115128/000119312523228644/d846485d8k.htm.
- TRML, announced 2023-06-22. Announcement: https://www.sec.gov/Archives/edgar/data/1827506/000119312523171895/d501508d8k.htm. Outcome filing 8-K 2023-10-20: https://www.sec.gov/Archives/edgar/data/1827506/000119312523259403/d571384d8k.htm.
- Conformis Inc, announced 2023-06-23. Announcement: https://www.sec.gov/Archives/edgar/data/1305773/000130577323000032/cfms-20230622.htm. Outcome filing 8-K 2023-09-05: https://www.sec.gov/Archives/edgar/data/1305773/000114036123042455/brhc20058250_8k.htm.
- Sigilon Therapeutics, Inc., announced 2023-06-29. Announcement: https://www.sec.gov/Archives/edgar/data/1821323/000110465923076070/tm2319973d1_8k.htm. Outcome filing 8-K 2023-08-11: https://www.sec.gov/Archives/edgar/data/1821323/000119312523210739/d510415d8k.htm.
- IMNM, announced 2023-06-29. Announcement: https://www.sec.gov/Archives/edgar/data/1472012/000110465923076136/tm2320045d1_8k.htm. Outcome filing 8-K 2023-10-04: https://www.sec.gov/Archives/edgar/data/1472012/000110465923106592/tm2327438d1_8k.htm.
- Kaleyra, Inc., announced 2023-06-30. Announcement: https://www.sec.gov/Archives/edgar/data/1719489/000119312523180610/d450414d8k.htm. Outcome filing 8-K 2023-10-10: https://www.sec.gov/Archives/edgar/data/1719489/000119312523253538/d915044d8k.htm.
- MEDS, announced 2023-06-30. Announcement: https://www.sec.gov/Archives/edgar/data/1382574/000149315223023016/form8-k.htm. Outcome filing 8-K 2023-07-31: https://www.sec.gov/Archives/edgar/data/1382574/000149315223026024/form8-k.htm.

## 7. Does the function show useful calibration?

On these 18 deals the function's average prediction was 0.8937 and the share that closed was 88.9%. The gap between those two figures is +0.0049.

The probabilities span 0.0481 points, from 0.8781 to 0.9263. In this sample the filing flags moved the result only a few points around 0.90.

Terminated deals were predicted at 0.8895 on average, against 0.8943 for deals that closed.

The sample is too small for a stable conclusion, particularly because terminated deals are scarce. Treat every comparison below as preliminary.

This sample does not show that the filing flags improve on the training close rate. The bootstrap interval for the Brier difference includes zero.

Useful calibration would require probabilities that move when the chance of closing moves. Here most of the number is the fixed 0.90 starting point. The flags do not separate completed deals from terminated deals by enough to be a useful close-probability estimate on this sample.
