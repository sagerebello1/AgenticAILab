# DealRadar pre-announcement feasibility

Run at 2026-10-25T19:29Z. Production scoring code was called and was not edited.

**A historical test of pre-announcement ranking was not run.** No existing function emits the probability that a company will announce a deal. There are no valid pre-announcement probabilities to score, so no Brier score and no ROC AUC are reported.

## 1. What the pipeline scores

The live book is built by `server.scan`. It searches SEC EDGAR for an 8-K containing "agreement and plan of merger" or an SC TO-T containing "offer to purchase". `server.lookup_symbol` uses those same two searches for one company. A row is kept only when `workflow.listed_company` is true: the filing quotes a per-share cash price, and a stock price and a break price are both present.

`edgar.search_filings` always ends the search window on today's date. It has no argument for a historical prediction date.

Once a filing is in hand, two functions estimate the chance that the announced deal eventually closes:

- `quote.close_probability` starts at 0.90 and adjusts filing flags in log-odds. With no flags, this run returned **0.9000**.
- `terms.estimate_probabilities` starts at 0.93 and adds the same flags. With no flags, this run returned **0.930**.

Those two numbers are the starting points for an announced deal. They are not the probability that a deal will be announced. `server._search_company_deals` says this in the message it returns when a company has no merger filing: the unchanged company list is not a close chance of zero.

`data/model.json` exists: no. `model.load()` returned a model: no. The trained path in `server.build_deal` calls `features.vectorize` on the announcement text and then `model.predict`. With the file absent, that path does not run.

## 2. Which functions can run before an announcement

| Function | What it returns before an announcement | Acquisition probability |
|---|---|---|
| `edgar.find_company` | Company name and CIK for a ticker | No |
| `market.history`, `market.identity`, `market.index_quote` | Delayed daily prices | No |
| `market.contract` | No options chain. The module records that Yahoo's options endpoint returned HTTP 401 | No |
| `news.score` | A headline adjustment. This run, with no headlines, returned **0.000** and 0 headlines | No. `news.apply` only shifts a probability it is given |
| `workflow.listed_company` | This run, on a company with no filing and no offer, returned **False** | No |
| `quote.respond` with no offer | This run raised: Need offer, spot, downside and days, or a sample id (s1 to s5). | No |

`features.vectorize` on empty text produced 33 features. The only nonzero names were: none. The extracted offer was None. An all-zero filing vector is not a pre-announcement score, and nothing in the server turns it into one while `model.load()` is empty.

## 3. Which functions need the announcement

- `terms.extract_terms` and both close-probability functions read flags from the merger or tender filing. Those flags are the offer form, antitrust language, financing, a vote, a tender, and a go-shop. They are not knowable from the company alone.
- `quote.respond` and `workflow.recalculate` also need the cash offer, the stock price, and the break price. The offer comes from the filing. The probability itself does not use the stock price.
- `pricing.scenario_value` and `options.analyze` value an option on an announced cash deal. They take `p_close` as an input.
- `training/collect.py` gathers historical 8-Ks that already contain a merger agreement. `training/label.py` then labels whether that announced deal closed. The training features in `features.py` are taken from the announcement text.
- `news.apply` moves an existing close probability. Its weights are hand-set, and the module says there is no historical headline dataset. A headline feed read today can mention an announcement that has already happened.

## 4. Whether a pre-announcement probability exists

No. The probe did not produce one.

Calling the close-probability function with empty flags returns 0.9000 from `quote.close_probability` and 0.930 from `terms.estimate_probabilities`. Using either number as the chance a company will be acquired would repeat the mistake rejected in the first validation: the app does not assign that number to a company with no filing.

A worked example from the closing-validation set shows the gap. CIRCOR's merger agreement was filed on 2023-06-05, and that packet is what `quote.close_probability` scored. A prediction date of 2023-06-04 would need inputs that existed that day. The flags in the 2023-06-05 filing did not exist yet. The code has no other feature vector for CIRCOR on 2023-06-04, and `search_filings` cannot be asked for "filings visible on 2023-06-04" because the window always ends today.

The same block applies to any of the other 17 scored deals, and to companies with no later announcement. Positive and negative cases would both be unscored. A Brier score or a ROC AUC on invented scores would not be an evaluation.

## 5. What is missing

- A function whose output is the probability of an announcement inside a stated horizon, such as 90 days.
- Inputs that exist before the filing. Prices can be read from `market.history` for a past date, but no probability function accepts them. Options premiums are unavailable. There is no saved history of headlines, fundamentals, or ownership.
- An as-of date on the EDGAR search, so a test can see only filings that were public on the prediction date.
- A labeled set of companies that were not announced, built without using the later outcome to choose the score.

## 6. Smallest change that would make a test possible

Add one new scoring function that takes only pre-announcement inputs and returns a probability of an announcement within a fixed horizon. Point the EDGAR search at a historical as-of date, and save the inputs as of that date. Then score companies that later announced and companies that did not, over the same horizon.

Saving the current filing flags earlier cannot do this. Those flags are parsed from the announcement. The 0.90 and 0.93 constants should not be reused as the pre-announcement score. This experiment does not add that function and does not change `quote.close_probability`.
