# Deal Radar

A local tool that scans new merger filings on SEC EDGAR, reads the deal terms, and tells you whether an
option on the target company looks cheap, fair or expensive. It is a research prototype, not investment advice.

## Run it

    python3 server.py        # then open http://127.0.0.1:8000

Python 3.9 or newer, standard library only. The running app uses public SEC filings and public Yahoo prices. It does not call a paid API, and it does not fill the screen with fictional companies when a source is down.

1. Create `.env` next to `server.py`.
2. Set `EDGAR_USER_AGENT` to your name and email. The SEC requires this contact and does not require a key or a credit card.

If EDGAR or Yahoo does not answer, the page shows that error and leaves the list empty.

## Train the close-probability model on past EDGAR deals

The server runs without training (it uses hand-written rules). To replace the rules with a model trained on
history, run these on your own computer. They need `pip install -r requirements-training.txt` and `EDGAR_USER_AGENT` in `.env`.

    python3 training/collect.py candidates --start 2005-01-01   # merger-agreement 8-Ks, one week at a time
    python3 training/collect.py text                            # download each announcement
    python3 training/collect.py submissions                     # download each company's filing history
    python3 training/label.py --verify --audit 30               # closed or terminated, then check 30 by hand
    python3 training/train.py                                   # fit, test, write data/model.json

Add `--limit 50` to a collect stage for a trial run. Collection is resumable and takes hours because the SEC allows
about 10 requests per second. `python3 training/train.py --demo` runs the whole training code on synthetic data
to prove it works; it only writes `data/model.demo.json`, which the server refuses to load.

What `train.py` does: it splits deals by date (oldest 70% to fit, next 15% to tune, newest 15% to test), compares a
logistic regression with gradient boosting, and prints Brier score, log loss, AUC and a calibration table next to two
baselines, "always predict the historical close rate" and the old hand-written rules. Restart `server.py` and the
interface shows the model's test scores in the "What the agent read" card. Deal timing curves learned from the same
data replace the guess for "chance the deal is decided before the option expires".

Limits you should know before trusting it:

- Outcomes are inferred, not given. A deal counts as closed when the filer's next decisive filing is Item 2.01 or 5.01,
  Form 25 or Form 15-12, and as terminated on a verified Item 1.02. Some labels will be wrong. That is why `--audit` exists.
- Only deals that resolve within 540 days are used, and only filings by the target company by default. Small
  acquisitions by large buyers often never file a completion notice, so they drop out.
- The model sees only what is in the announcement filing. The strongest known predictor of whether a deal closes is the
  market's own spread between price and offer, which is not a feature yet. Adding it needs historical prices.
- Roughly nine in ten announced deals close, so terminated deals are scarce. Check the test-set size and calibration
  table before trusting any single probability. If the model does not beat "base rate" on the test set, do not use it.

## Live news and prices from Yahoo Finance

When a deal has a ticker, the interface reads Yahoo's public headline feed and shifts the close odds by a bounded
amount (at most 1.5 log-odds points) using hand-set rules, for example "FTC sues to block" (down) or "shareholders
approve" (up). Those weights are judgments, not trained, and every headline that moved the odds is listed so you can
overrule it. "Pull live prices from Yahoo" fills today's price, the last close before the announcement (the "deal
breaks" price). Yahoo has no official API for these, so they can break or rate-limit without notice.
Yahoo's options-chain endpoint returned HTTP 401 on 19 October 2026. The app does not work around that,
and it does not invent a premium. Type a bid and ask if you want the call and put scenarios.

## How the value is worked out

Plain Black-Scholes treats a stock as a random walk. A takeover target is pinned to the offer, so the tool prices the
contract in three worlds and weights them:

| Outcome | Stock trades at | Volatility |
|---|---|---|
| Deal closes before expiry | offer (plus optional pop) | 12% cash, 0.9 x normal for stock deals |
| Still unresolved at expiry | p x offer + (1 - p) x fallback | 18% |
| Deal breaks before expiry | fallback (pre-deal) price | normal |

Weights: closes = P(close) x P(decided before expiry); breaks = (1 - P(close)) x P(decided); unresolved = 1 - P(decided).
P(decided before expiry) comes from comparing days to expiry with days to the expected close. Verdict: Buy if model value is
at least 20% above the premium, Fair if no more than 10% below, otherwise Avoid. Those cutoffs are rules of thumb.

`pricing.py` is the reference; the JavaScript in `static/app.html` mirrors it (checked to match to 5 decimals).

## Files

- `server.py` local web server and API (`/api/scan`, `/api/status`, `/api/enrich`)
- `edgar.py` EDGAR full-text search, filing download, rate limiting
- `terms.py` reads a filing (price, cash or stock, expected close, approvals, conditions) and scores the odds with transparent rules
- `features.py` turns a filing into model inputs; `model.py` scores with the trained weights
- `training/` collect.py, label.py, train.py (see above)
- `news.py` Yahoo headlines to an odds adjustment; `market.py` Yahoo prices, volatility and option quotes
- `pricing.py` Black-Scholes and the three-scenario model
- `llm.py` and `dealroom.py` are not imported by the server. Both need a paid account, so the app does not call them.
- `sample_data.py` holds fictional deals used only by `python3 quote.py` to check the quote math. The server refuses those ids.

## What is and is not tested

- Tested: pricing math (textbook values, put-call parity, JS vs Python), term extraction on synthetic filing text, the server in sample mode, the interface in a browser, the training code on synthetic data, the labelling rules on hand-made filing histories, the news rules on made-up headlines, and the live scan path with EDGAR and Yahoo mocked.
- Not tested: real EDGAR, Yahoo and Dealroom traffic, the Claude extraction step, and training on real data. The build environment could not reach any of them, so no real model has been trained and no accuracy figure exists yet. Expect to adjust queries or field names on first run.
- EDGAR full-text search is not an officially documented SEC API and can change. The SEC's published limit is 10 requests per second, and this client waits 0.12 seconds between requests.
- Yahoo's chart and headline feeds are public and unofficial. They can change or rate-limit. A failure is shown on the deal; a price is not invented.
- Dealroom and Anthropic are paid services. They are not called.
- The close probabilities are judgment-based starting points, not a fitted model.
