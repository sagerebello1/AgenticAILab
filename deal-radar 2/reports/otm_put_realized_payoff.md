# OTM put realized-payoff coverage

This report reads the historical SQLite file. It does not price an option with Black-Scholes, and it does not call a data provider.

## What was measured

- Verified deals are target filings that are not amendments and not same-week duplicates.
- The research put is struck at 80% of the last stored close before the announcement. That strike is not a listed contract.
- The realized payoff is the undiscounted intrinsic value at the close 30 trading sessions after the announcement: max(strike - later close, 0).
- A row is scored only when the filing says cash, an offer price is stored, the prior close is stored, and the later close is stored.
- No option premium is subtracted, because no historical option premium is stored.

## Coverage

- Verified deals: 749
- Offer price stored: 124
- Consideration stored: 155 (cash 122, stock 31, mixed 2, other 0)
- Exchange ratio stored: 33
- Standalone stock price, the last stored close before the announcement: 237
- Outcome table price before announcement: 237
- Outcome table close 30 sessions later: 237
- Deals whose ticker has at least one stored daily close: 238
- Deals with a stored close 30 sessions after the announcement: 237

## Missing

- Offer price: 625
- Consideration: 594
- Exchange ratio: 716
- Standalone stock price: 512
- Historical daily closes for the target ticker: 511
- Announcement date: 0
- Close 30 trading sessions later: 512
- Not a cash deal, so no payoff was calculated: 627

## Realized payoffs

- Deals scored: 7
- Finished with a positive intrinsic value: 0
- Finished worthless: 7
- Average intrinsic value per share: 0.0000

| Ticker | Announcement | Offer | Prior close | Research strike | Later close | Intrinsic |
| --- | --- | --- | --- | --- | --- | --- |
| HBNC | 2016-03-11 | 17.50 | 10.62 | 8.4942 | 10.97 | 0.0000 |
| TSN | 2017-04-28 | 40.25 | 64.61 | 51.6880 | 61.27 | 0.0000 |
| LLY | 2019-01-07 | 235.00 | 114.66 | 91.7280 | 122.66 | 0.0000 |
| CNR | 2022-03-07 | 24.65 | 35.92 | 28.7360 | 47.33 | 0.0000 |
| CVS | 2023-02-08 | 39.00 | 85.98 | 68.7840 | 72.37 | 0.0000 |
| GILD | 2024-02-12 | 32.50 | 73.67 | 58.9360 | 72.41 | 0.0000 |
| GILD | 2026-02-23 | 115.00 | 151.40 | 121.1200 | 138.80 | 0.0000 |

## Realized-payoff error and market pricing error

- Realized-payoff error against Black-Scholes or the M&A scenario model: not computed. Both models need an implied volatility, and this database does not store one. None was filled in.
- Options-market pricing error: not computed. The database has no historical option bid, ask, or implied volatility. The stored observed premium is the stock's offer premium, not an option premium, and it was not used.
- The intrinsic values above are the put's stock-path payoff. They are not a statement that either model was right or wrong.

## Assumptions and limits

- Stock and mixed deals are counted in the coverage and are not scored. A stock deal needs the acquirer's price, which is not stored on the announcement.
- The 30-session close is the same offset the dataset builder stores. It is not an option expiration date from an exchange.
- The research strike is below the prior close by construction. It is one assumption, not a search over strikes.
- A stored offer is used as stored. It was not dropped when it sits far from the prior close, and it was not corrected.
- Daily closes are the stored Yahoo chart closes. A missing bar is not replaced.
- This file does not change the live pricing engine, the server, or the screen.
