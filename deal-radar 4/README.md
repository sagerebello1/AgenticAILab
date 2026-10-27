# Deal Radar

A local tool that scans new merger filings on SEC EDGAR, reads the deal terms, and tells you whether an
option on the target company looks cheap, fair or expensive. It is a research prototype, not investment advice.

## Run it

    python3 server.py        # then open http://127.0.0.1:8000

Python 3.9 or newer, standard library only. With no setup it runs on five made-up sample deals. To go live:

1. Copy `.env.example` to `.env`.
2. Set `EDGAR_USER_AGENT` to your name and email. The SEC requires this and needs no key.
3. Optional: add Dealroom keys (`DEALROOM_CLIENT_ID`, `DEALROOM_CLIENT_SECRET`) and an `ANTHROPIC_API_KEY`.

`python3 make_standalone.py` writes `dist/deal-radar-demo.html`, a single file that works offline in sample mode.

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

## Live news and prices from Yahoo Finance (and Bloomberg headlines you paste)

When a deal has a ticker and the local server is running, the interface reads Yahoo's public headline feed and shifts
the close odds using hand-set rules, for example "FTC sues to block" (down) or "shareholders approve" (up). Newer
headlines count more (10-day half-life). The total shift is capped at 1.5 log-odds points, and at 4 if a headline says
the deal was terminated or completed, in which case the page shows a red notice to confirm in the filings. Those weights
are judgments, not trained. Every headline that moved the odds is listed so you can overrule it.

Bloomberg Terminal has no feed this tool can read. Open the "Add headlines from Bloomberg or anywhere else" box under
the news list, paste headlines one per line (optionally starting with a date such as 2026-10-12), and they are scored
with the same rules as Yahoo's. This works in the hosted demo too, because the scoring runs in the browser. The
Portfolio sheet uses the same news-adjusted odds as the Deals sheet.

"Pull live prices from Yahoo" fills today's price, the last close before the announcement (the "deal breaks" price),
pre-announcement volatility and, if `pip install yfinance` is done, a real option quote. In the Portfolio sheet, typing a
ticker looks up its name, price and a beta computed from two years of daily returns against SPY (`/api/quote`). Yahoo has
no official API for these, so they can break or rate-limit without notice.

## Live prices all the time (Finnhub or Yahoo)

Run `python3 server.py` and the page keeps itself current. A strip under the header shows SPY, every deal ticker
and every portfolio ticker with price and day change, and flashes on each move. Deal stock prices, the gap to the
offer, the verdict, and the Portfolio sheet's value and risk numbers all re-calculate as prices arrive (the
portfolio at most every 5 seconds).

- **With a free Finnhub key** (sign up at finnhub.io, put it in `.env` as `FINNHUB_API_KEY`): the server opens one
  WebSocket to Finnhub and every trade is pushed to your browser the moment it happens. A background poller also
  reads Finnhub's `/quote` (for the day change, and as a backup if the stream drops). The poller stays under 45
  calls a minute and pauses for 30 seconds on HTTP 429. Finnhub's company-news feed is also merged into the news
  that moves the close odds. Free-plan limits change (when this was written: about 60 calls a minute and 50
  streaming symbols), so check your plan.
- **Without a key:** the server polls Yahoo Finance's chart endpoint. Those prices are usually delayed about 15
  minutes, the endpoint is unofficial, and it can rate-limit without notice. The strip says so.
- **Your own numbers win.** If you type a stock price, it stops being overwritten (the page shows "YOURS" and a
  "use live" link). Same for an option premium.
- **Option quotes** are not part of Finnhub's free plan. With `pip install yfinance` you can tick "Refresh this
  option quote every minute" on a deal; those quotes come from Yahoo and are delayed.
- **News** for deals that were already loaded is re-read every 5 minutes.
- Outside US trading hours (9:30 to 16:00 Eastern, weekdays; holidays are not known) the strip says the market is
  closed and polling slows to every 90 seconds.
- Only the real EDGAR scan feeds tickers into the live stream. Sample deals have made-up tickers and are never
  sent to the data provider. The hosted demo page cannot open a live connection at all.

## Portfolio sheet: alpha, beta and fit with your risk tolerance

The second tab, **Portfolio**, measures a portfolio you upload and links it to the deals on the first tab.

1. **Load holdings.** Upload a CSV (`ticker,type,quantity,strike,expiry,price,beta`), paste one, or edit the table. Types are stock, call, put and cash. A holding in a company that appears on the Deals sheet is linked to that deal, and you can change its close chance right in the table.
2. **Price history.** Run the local server and it pulls about two years of daily closes from Yahoo Finance against SPY. Without the server, upload your own history CSV (one date column, one closing-price column per ticker, and a SPY column). The built-in sample portfolio uses simulated history and is labelled as such.
3. **Set your risk preferences.** Pick Conservative, Moderate or Aggressive, then adjust the largest loss you accept, horizon, beta range, most in any one deal, lowest close chance you will hold, and how strongly deal failures cluster when markets fall.

What it reports:

- **Beta and alpha (history):** today's holdings replayed over past returns and regressed on the market after the risk-free rate. Options count by their delta. Alpha is shown a year at a time with a t-statistic, and the page says so when it is not statistically different from zero.
- **Beta, deal-adjusted:** a deal holding's beta is scaled by its chance of breaking. This is a rule of thumb, not a fitted result.
- **Forward alpha:** every non-deal holding is assumed to earn beta times the market premium, so any extra expected return comes from the deal positions and their close odds.
- **Worst case:** a 4,000-path simulation of the horizon. Each deal closes, stays pending or breaks by your odds, and options are re-priced with Black-Scholes at each outcome.
- **Checks and tips:** pass or outside for beta, worst-case loss, largest deal position and weakest deal odds, with plain suggestions such as how many shares to sell to reach your cap.

Limits: past betas change, stock-specific risk is treated as independent across holdings, dividends, taxes and trading costs are ignored, and the deal sample is only as good as the close odds fed in. Your portfolio file is read in the browser and kept in its local storage; it is never sent anywhere except ticker symbols to Yahoo Finance when you run the local server.

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
- `static/app.html` the interface, including the Portfolio sheet (its maths is in the second script block)
- `live.py` live price feed (Finnhub WebSocket and REST, Yahoo fallback, server-sent events to the page); `news.py` Yahoo and Finnhub headlines to an odds adjustment; `market.py` Yahoo prices, volatility and option quotes
- `llm.py` optional: a Claude model reads the filing instead of the text rules
- `dealroom.py` optional: company profile lookup
- `pricing.py` Black-Scholes and the three-scenario model
- `sample_data.py` fictional deals

## What is and is not tested

- Tested: pricing math (textbook values, put-call parity, JS vs Python), term extraction on synthetic filing text, the server in sample mode, the interface in a browser, the training code on synthetic data, the labelling rules on hand-made filing histories, the news rules on made-up headlines, the live scan path with EDGAR and Yahoo mocked, and the portfolio maths (regression against a known beta, simulation against closed-form answers, uploads in a browser).
- Live feed: tested end to end only against a fake Finnhub (REST and WebSocket) built for the test: streaming, reconnect after a dropped socket, un-subscribing, HTTP 429 back-off, a browser receiving prices and updating deals and the portfolio. The WebSocket client is hand-written (no extra packages) and has not talked to the real Finnhub.
- Not tested: real EDGAR, Yahoo, Finnhub and Dealroom traffic, the Claude extraction step, and training on real data. The build environment could not reach any of them, so no real model has been trained and no accuracy figure exists yet. Expect to adjust queries or field names on first run.
- EDGAR full-text search is not an officially documented SEC API and can change.
- Dealroom (dealroom.co) covers mostly private and venture-backed companies, so large listed targets often have no match. It is not the same product as DealRoom (dealroom.net).
- Neither source has stock or option prices. Live deals start with placeholder market numbers, marked in orange, that you must replace with broker quotes.
- The close probabilities are judgment-based starting points, not a fitted model.
