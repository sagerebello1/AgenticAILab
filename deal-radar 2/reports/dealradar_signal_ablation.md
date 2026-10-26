# DealRadar filing-flag ablation

Run at 2026-10-25T19:06Z. The 18 deals and their outcomes are the scored set in `reports/dealradar_closing_validation.md`. Announcement text was reread from the packets saved for that test. No new transactions were selected.

**These results are preliminary.** Two of the 18 deals were terminated. A difference this small, on this few failures, does not support a claim of statistical significance.

`quote.close_probability` was called and was not edited. The flat 90% row and the flag-off row are calculated in this script.

## 1. Baseline versus the existing model

A is a constant 0.90, the starting value in `quote.BASE_P`. B is `quote.close_probability` on the announcement flags. C calls the same function with an empty flag dict, so none of the adjustments run.

A and C match. The largest gap between them on any deal is 1.11e-16.

| Model | Mean probability | Closed deals | Terminated deals | Mean Brier |
|---|---|---|---|---|
| A. 90% for every deal | 0.9000 | 0.9000 | 0.9000 | 0.0989 |
| B. Existing flags | 0.8937 | 0.8943 | 0.8895 | 0.0981 |
| C. Flags disabled | 0.9000 | 0.9000 | 0.9000 | 0.0989 |

DealRadar Brier minus the 90% Brier: **-0.0008**. A negative number would mean the flags scored better.

A 2,000-draw bootstrap of these 18 deals put that difference between **-0.0041** and **+0.0022** (2.5th to 97.5th percentile). The interval includes zero.

ROC AUC for the flag model: **0.500**. With two terminated deals and scores packed between 0.8781 and 0.9263, this rank is not a meaningful measure of discrimination. The 90% model assigns the same score to every deal, so it has no ranking to compare.

## 2. Deal-by-deal scores

Brier score = (probability − outcome)². Closed is 1 and terminated is 0.

| Company | Announced | Outcome | 90% probability | Flag probability | Flags off | 90% Brier | Flag Brier |
|---|---|---|---|---|---|---|---|
| CIRCOR INTERNATIONAL INC | 2023-06-05 | Closed | 0.9000 | 0.8781 | 0.9000 | 0.0100 | 0.0148 |
| AirJoule Technologies Corp. | 2023-06-05 | Closed | 0.9000 | 0.8781 | 0.9000 | 0.0100 | 0.0148 |
| Clover Leaf Capital Corp. | 2023-06-06 | Terminated | 0.9000 | 0.8895 | 0.9000 | 0.8100 | 0.7913 |
| Paratek Pharmaceuticals, Inc. | 2023-06-07 | Closed | 0.9000 | 0.8781 | 0.9000 | 0.0100 | 0.0148 |
| LIMEADE, INC | 2023-06-09 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |
| NASDAQ, INC. | 2023-06-12 | Closed | 0.9000 | 0.8781 | 0.9000 | 0.0100 | 0.0148 |
| CHINOOK THERAPEUTICS, INC. | 2023-06-12 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |
| GELESIS HOLDINGS, INC. | 2023-06-13 | Terminated | 0.9000 | 0.8895 | 0.9000 | 0.8100 | 0.7913 |
| NEXTIER OILFIELD SOLUTIONS INC. | 2023-06-15 | Closed | 0.9000 | 0.9096 | 0.9000 | 0.0100 | 0.0082 |
| Coherus Oncology, Inc. | 2023-06-16 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |
| DICE Therapeutics, Inc. | 2023-06-20 | Closed | 0.9000 | 0.9183 | 0.9000 | 0.0100 | 0.0067 |
| Quotient Technology Inc. | 2023-06-20 | Closed | 0.9000 | 0.9000 | 0.9000 | 0.0100 | 0.0100 |
| Tourmaline Bio, Inc. | 2023-06-22 | Closed | 0.9000 | 0.9263 | 0.9000 | 0.0100 | 0.0054 |
| Conformis Inc | 2023-06-23 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |
| Sigilon Therapeutics, Inc. | 2023-06-29 | Closed | 0.9000 | 0.9263 | 0.9000 | 0.0100 | 0.0054 |
| Immunome Inc. | 2023-06-29 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |
| Kaleyra, Inc. | 2023-06-30 | Closed | 0.9000 | 0.8781 | 0.9000 | 0.0100 | 0.0148 |
| Scienture Holdings, Inc. | 2023-06-30 | Closed | 0.9000 | 0.8895 | 0.9000 | 0.0100 | 0.0122 |

## 3. Filing flags

Frequency is counted on these 18 announcements. "Applied" is the count that changed `quote.close_probability`. A shareholder vote is read from the filing even when a tender offer is also present, and the formula then ignores the vote. The contribution is the average change in probability from removing that flag on the deals where the formula used it.

The close rates are descriptive. None of these splits has five deals on both sides, which is the minimum used here before treating a comparison as even a weak observation. They are not evidence that a flag causes a deal to close or fail.

| Flag | Deals where the text has it | Deals where the formula uses it | Close rate when present | Close rate when absent | Mean probability contribution | Enough to judge? |
|---|---|---|---|---|---|---|
| HSR | 10 of 18 | 10 | 100.0% | 75.0% | -0.0104 | No |
| Second request | 0 of 18 | 0 | — | 88.9% | — | No |
| Foreign regulator | 0 of 18 | 0 | — | 88.9% | — | No |
| Sector regulator | 1 of 18 | 1 | 100.0% | 88.2% | -0.0288 | No |
| Financing condition | 0 of 18 | 0 | — | 88.9% | — | No |
| No financing condition | 7 of 18 | 7 | 85.7% | 90.9% | 0.0099 | No |
| Tender offer | 5 of 18 | 5 | 100.0% | 84.6% | 0.0279 | No |
| Shareholder vote | 16 of 18 | 12 | 87.5% | 100.0% | -0.0108 | No |
| Go-shop | 1 of 18 | 1 | 0.0% | 94.1% | -0.0105 | No |
| Stock consideration | 0 of 18 | 0 | — | 88.9% | — | No |

- **HSR.** The announcement mentions a US antitrust filing (Hart-Scott-Rodino). Present in 10 deals. Higher closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Second request.** The announcement mentions a second request from antitrust regulators. Present in 0 deals. It does not appear, so there is no association to report. There are not enough observations to conclude anything about this flag.
- **Foreign regulator.** The announcement names a foreign regulator. Each name, up to three, subtracts 0.03. Present in 0 deals. It does not appear, so there is no association to report. There are not enough observations to conclude anything about this flag.
- **Sector regulator.** The announcement names a sector regulator. Each name, up to two, subtracts 0.03. Present in 1 deal. Higher closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Financing condition.** The announcement says closing depends on financing. Present in 0 deals. It does not appear, so there is no association to report. There are not enough observations to conclude anything about this flag.
- **No financing condition.** The announcement says there is no financing condition. Present in 7 deals. Lower closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Tender offer.** The announcement describes a tender offer. If this is set, the vote adjustment is not applied. Present in 5 deals. Higher closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Shareholder vote.** The announcement requires a shareholder vote. The formula uses it only when there is no tender. Present in 16 deals. Lower closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Go-shop.** The announcement describes a go-shop period. Present in 1 deal. Lower closing rate when present, in this sample only. There are not enough observations to conclude anything about this flag.
- **Stock consideration.** The consideration is the buyer's stock. Cash and mixed consideration do not move the probability. Present in 0 deals. It does not appear, so there is no association to report. There are not enough observations to conclude anything about this flag.

## 4. Sensitivity of each flag

Each row turns on only that input and calls `quote.close_probability`. The log-odds change matches `points / 0.09` from the function. Production code was not edited to produce these rows.

Every isolated toggle on these 18 deals moved the log-odds by the amount in the existing point schedule, including the rule that a tender offer replaces the vote adjustment. No mismatch was found.

| Flag | Points in the formula | Probability with only this flag | Change from 0.90 |
|---|---|---|---|
| HSR | -0.01 | 0.8895 | -0.0105 |
| Second request | -0.10 | 0.7476 | -0.1524 |
| Foreign regulator | -0.03 | 0.8657 | -0.0343 |
| Sector regulator | -0.03 | 0.8657 | -0.0343 |
| Financing condition | -0.06 | 0.8221 | -0.0779 |
| No financing condition | +0.01 | 0.9096 | +0.0096 |
| Tender offer | +0.02 | 0.9183 | +0.0183 |
| Shareholder vote | -0.01 | 0.8895 | -0.0105 |
| Go-shop | -0.01 | 0.8895 | -0.0105 |
| Stock consideration | -0.02 | 0.8781 | -0.0219 |

Toggling a flag on a real deal changes the probability by less or more than the one-flag row above, because the logistic curve is steeper near 0.50 than near 0.90. The log-odds change stays equal to the point value divided by 0.09. That check passed for every deal and every flag.

Average probability change when the flag is switched on for deals that did not already have it, and switched off for deals that did:

| Flag | Mean change when switched on | Mean change when switched off |
|---|---|---|
| HSR | -0.0105 | 0.0104 |
| Second request | -0.1582 | Not used on these deals |
| Foreign regulator | -0.0359 | Not used on these deals |
| Sector regulator | -0.0359 | 0.0288 |
| Financing condition | -0.0877 | Not used on these deals |
| No financing condition | 0.0107 | -0.0099 |
| Tender offer | 0.0290 | -0.0279 |
| Shareholder vote | -0.0017 | 0.0108 |
| Go-shop | -0.0110 | 0.0105 |
| Stock consideration | -0.0230 | Not used on these deals |

The shareholder-vote average is smaller than the one-flag row because a tender offer blocks that adjustment. On a filing that already has a tender, switching the vote flag on does not change the probability.

## 5. Limits

- Two terminated deals, Clover Leaf and Gelesis, carry almost all of the Brier score. Both were scored at 0.8895, against 0.9000 with the flags off. The flags helped those two rows by a few thousandths and moved the closed deals by a similar amount in both directions.
- Sixteen closed deals have Brier scores near 0.01 either way. They cannot show whether a rare failure is being detected.
- Second request, a financing condition, foreign approval, and stock consideration do not appear in this set. The flags that do appear move the probability by about one to four points.
- Vote and tender overlap. Gelesis has a vote in the text, and the formula still applies the vote adjustment because that filing has no tender. Deals with both a tender and a vote keep only the tender adjustment.
- The close rates above describe these 18 filings. They were already chosen by the closing validation, which kept deals with a clear later outcome sentence. This ablation does not add deals and does not drop deals based on a new look at the outcomes.
- The 0.90 baseline here is the constant inside the function. It is not the 97% close rate from the earlier training window.

## 6. Do the flags add predictive value?

On these 18 deals, no. The flag model has a mean Brier score of 0.0981 and the flat 90% model has 0.0989. The difference is -0.0008, and the bootstrap interval includes zero. Disabling the flags returns exactly 0.90, so the small gap is the whole effect of the adjustments.

The two terminated deals were not given a meaningfully lower probability than the deals that closed (0.8895 versus 0.8943). The ranking score does not show separation.

A stronger test needs more terminated deals with announcement packets saved the same way, enough that several failures carry each common flag. Second request, financing conditions, and stock consideration need to be present in more than a handful of deals before their point values can be checked against outcomes. A useful sample would also keep the deals whose outcome filing was ambiguous, instead of scoring only the ones with a clear closing or termination sentence.
