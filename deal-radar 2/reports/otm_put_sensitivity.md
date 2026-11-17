# OTM put sensitivity

This report prices one hypothetical put with the existing Black-Scholes function and the existing three-scenario function. It does not use a market premium, and it does not say which price is more accurate.

## Hypothetical contract

The anchor is not a historical deal. A missing historical input was not filled with one of these numbers.

| Input | Value |
| --- | --- |
| Stock price | 50.000000 |
| Strike | 40.000000 |
| Days to expiration | 90 |
| Expected days to close | 120 |
| Rate | 0.045000 |
| Volatility | 0.350000 |
| Cash offer | 60.000000 |
| Downside | 32.000000 |
| Close probability | 0.700000 |
| Pending probability | 0.600000 |
| Market premium | not supplied |

One input changes in each table. The others stay at the anchor. The year fraction is days divided by 365 in both models.

## Historical deals that were not priced

`historical_stock_prices` stores a daily stock close. It does not store an option quote or an implied volatility. The seven cash deals below have an offer and a prior stock close in the realized-payoff report. They were passed to the benchmark with the option terms left empty. Both prices stayed empty.

Missing on every one of these deals: implied volatility, listed strike, expiration, option bid, option ask, last-trade timestamp.

| Ticker | Announcement | Stored offer | Stored prior close | Black-Scholes | M&A-aware |
| --- | --- | --- | --- | --- | --- |
| HBNC | 2016-03-11 | 17.500000 | 10.620000 | — | — |
| TSN | 2017-04-28 | 40.250000 | 64.610000 | — | — |
| LLY | 2019-01-07 | 235.000000 | 114.660000 | — | — |
| CNR | 2022-03-07 | 24.650000 | 35.920000 | — | — |
| CVS | 2023-02-08 | 39.000000 | 85.980000 | — | — |
| GILD | 2024-02-12 | 32.500000 | 73.670000 | — | — |
| GILD | 2026-02-23 | 115.000000 | 151.400000 | — | — |

## Close probability

| Close probability | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 0.000000 | 0.316804 | 3.076179 | 2.759375 | 0.388889 | yes |
| 0.250000 | 0.316804 | 2.309035 | 1.992231 | 0.388889 | yes |
| 0.500000 | 0.316804 | 1.541890 | 1.225087 | 0.388889 | yes |
| 0.700000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 0.900000 | 0.316804 | 0.314459 | -0.002344 | 0.388889 | yes |
| 1.000000 | 0.316804 | 0.007601 | -0.309202 | 0.388889 | yes |

The pending probability stays at 0.60 in this table. It is a separate input.

| Pending probability | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 0.000000 | 0.316804 | 5.545468 | 5.228664 | 0.388889 | yes |
| 0.300000 | 0.316804 | 1.558399 | 1.241596 | 0.388889 | yes |
| 0.600000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 0.840000 | 0.316804 | 0.920618 | 0.603815 | 0.388889 | yes |
| 1.000000 | 0.316804 | 0.920574 | 0.603771 | 0.388889 | yes |

## Offer price

| Cash offer | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 30.000000 | 0.316804 | 8.876580 | 8.559776 | 0.388889 | yes |
| 40.000000 | 0.316804 | 3.054692 | 2.737889 | 0.388889 | yes |
| 50.000000 | 0.316804 | 1.154086 | 0.837282 | 0.388889 | yes |
| 60.000000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 80.000000 | 0.316804 | 0.920574 | 0.603770 | 0.388889 | yes |
| 120.000000 | 0.316804 | 0.920573 | 0.603770 | 0.388889 | yes |

## Deal-break downside

| Downside | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 15.000000 | 0.316804 | 3.199573 | 2.882769 | 0.388889 | yes |
| 25.000000 | 0.316804 | 1.743185 | 1.426381 | 0.388889 | yes |
| 32.000000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 40.000000 | 0.316804 | 0.297045 | -0.019758 | 0.388889 | yes |
| 50.000000 | 0.316804 | 0.036990 | -0.279813 | 0.388889 | yes |
| 70.000000 | 0.316804 | 0.000144 | -0.316660 | 0.388889 | yes |

## Implied volatility

The volatility column is the volatility supplied to both functions. The cash close scenario then replaces it with 0.12, and the pending scenario uses 0.18.

| Supplied volatility | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 0.100000 | 5.1786e-07 | 0.889441 | 0.889440 | 0.388889 | yes |
| 0.120000 | 2.5643e-05 | 0.889452 | 0.889426 | 0.388889 | yes |
| 0.180000 | 0.005443 | 0.890536 | 0.885093 | 0.388889 | yes |
| 0.250000 | 0.063048 | 0.898665 | 0.835617 | 0.388889 | yes |
| 0.350000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 0.500000 | 1.018515 | 1.001430 | -0.017084 | 0.388889 | yes |
| 0.800000 | 2.998638 | 1.195585 | -1.803054 | 0.388889 | yes |

## Time to expiration

The expected close stays at 120 days. Resolve is 0.03 at or below 40 percent of that time and 0.97 at or above 130 percent.

| Days to expiration | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 15.000000 | 0.000653 | 0.071341 | 0.070687 | 0.030000 | yes |
| 30.000000 | 0.018371 | 0.070856 | 0.052485 | 0.030000 | yes |
| 47.000000 | 0.075355 | 0.071178 | -0.004177 | 0.030000 | yes |
| 48.000000 | 0.079714 | 0.071251 | -0.008464 | 0.030000 | yes |
| 49.000000 | 0.084165 | 0.071331 | -0.012834 | 0.030000 | yes |
| 90.000000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 119.000000 | 0.506348 | 1.580505 | 1.074157 | 0.657407 | yes |
| 120.000000 | 0.512968 | 1.603113 | 1.090145 | 0.666667 | no |
| 121.000000 | 0.519589 | 1.625726 | 1.106136 | 0.675926 | no |
| 155.000000 | 0.743622 | 2.347196 | 1.603574 | 0.970000 | no |
| 156.000000 | 0.750137 | 2.348054 | 1.597917 | 0.970000 | no |
| 157.000000 | 0.756647 | 2.348913 | 1.592266 | 0.970000 | no |
| 200.000000 | 1.029809 | 2.386046 | 1.356238 | 0.970000 | no |

## Cash, stock, and mixed

Each structure is set to an acquisition level of 60. The stock case is an exchange ratio of 0.5 and an acquirer price of 120. The mixed case is 20 in cash plus a ratio of 0.4 on an acquirer price of 100.

| Consideration | Level | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Close-scenario put |
| --- | --- | --- | --- | --- | --- |
| cash | 60.000000 | 0.316804 | 0.928175 | 0.611371 | 5.4410e-13 |
| stock | 60.000000 | 0.316804 | 0.930648 | 0.613844 | 0.009085 |
| mixed | 60.000000 | 0.316804 | 0.930648 | 0.613844 | 0.009085 |

## Stock price

| Stock price | Black-Scholes | M&A-aware | M&A minus Black-Scholes | Resolve | Expires before close |
| --- | --- | --- | --- | --- | --- |
| 35.000000 | 5.473670 | — | — | — | — |
| 40.000000 | 2.539540 | — | — | — | — |
| 41.000000 | 2.127339 | 0.928175 | -1.199165 | 0.388889 | yes |
| 50.000000 | 0.316804 | 0.928175 | 0.611371 | 0.388889 | yes |
| 70.000000 | 0.001234 | 0.928175 | 0.926941 | 0.388889 | yes |
| 100.000000 | 9.1115e-08 | 0.928175 | 0.928175 | 0.388889 | yes |

## Checks

- Every returned price is finite and non-negative. Every priced row's weights are between 0 and 1 and sum to 1. The M&A price stays inside the three scenario values.
- Black-Scholes in the benchmark and Black-Scholes in pricing.py use the same spot, strike, year fraction, rate, and volatility. The largest absolute gap on these rows is 0.
- While the put remains out of the money, the M&A price does not change with the stock price. The range across those spots is 0. At stock prices 35, 40 the benchmark still returns Black-Scholes and withholds the M&A price because the put is not out of the money.
- Calling the scenario formula directly at stock price 35 and stock price 50 returns the same M&A price, 0.928175. The formula replaces the stock price with the offer, the pending blend, and the downside before it prices the put. The benchmark's refusal at or above the strike is a gate, not a jump in that formula.
- With the other hypothetical inputs fixed, the M&A price moves in a straight line as the close probability goes from 0 to 1. The change is -3.068578. The midpoint of the two ends differs from the 0.50 result by 0. Black-Scholes does not use the close probability, so it stays at 0.316804.
- Changing the pending probability moves the pending stock level and the M&A price, from 0.920574 to 5.545468. It does not change the three weights. The pending probability is not the close probability.
- Raising volatility from 0.10 to 0.80 raises the Black-Scholes put from 0.000001 to 2.998638 and the M&A put from 0.889441 to 1.195585. In a cash deal the close scenario keeps volatility at 0.12 and the pending scenario keeps volatility at 0.18, so only the break scenario uses the supplied volatility.
- Across expiration of 10 through 200 days, with the expected close held at 120, the largest one-day M&A change is 0.022669 (day 143 to 144) and the largest one-day Black-Scholes change is 0.006623. Neither is a jump. At the expected-close boundary the one-day slopes are 0.022608 and 0.022613. The expires-before flag flips at that boundary, and the price does not.
- Resolve is flat at 0.03 until expiration reaches 40 percent of the time to close, then rises in a straight line, then stays at 0.97 from 130 percent. Those corners fall on day 48 and day 156. The M&A put's one-day change shifts by 0.000008 at day 48 and by 0.000001 at day 156. The weight rule has a corner. The put price does not jump.
- Cash, stock, and mixed are set so each acquisition level is 60. Black-Scholes is the same on all three, within 0. The M&A prices differ because a cash close uses volatility 0.12 and a stock or mixed close uses 90 percent of the supplied volatility: cash 0.928175, stock 0.930648, mixed 0.930648.
- Adding a hypothetical market premium of 1.25 does not change either theoretical price. The M&A gap is 0 and the Black-Scholes gap is 0. No market premium is used in the sweeps.
- When the option expires before the expected close, the benchmark still returns an M&A price of 0.070856 by lowering resolve to 0.03. black_scholes.acquisition_option_value returns no expected value for the same timing and says the acquisition price is not an option payoff. The benchmark follows pricing.scenario_value. It does not follow acquisition_option_value. Those two formulas are not interchangeable.
- Raising the cash offer from 30 to 120 changes the M&A put by -7.956007 and leaves Black-Scholes unchanged. On this grid the M&A put falls at every step, and the last steps are nearly flat because the close and pending puts are already worth about nothing.
- The largest pending-probability step is 3.987068, from 0.00 to 0.30. The pending stock level crosses the strike of 40 inside that step, so that scenario's put loses most of its value. The weights do not change.
- Raising the deal-break downside from 15 to 70 changes the M&A put by -3.199429 and leaves Black-Scholes unchanged. A downside above the offer is priced as written. It is not treated as a data error.

## Suggested improvements

None of these are implemented. The pricing functions were not changed.

- Show the scenario stock prices beside the market stock price. The M&A price does not respond to the market stock price while the put is out of the money, and a reader can otherwise think both models used the same underlying.
- State the volatility each scenario actually uses. A cash close does not use the supplied implied volatility.
- Keep `acquisition_option_value` out of this comparison. It refuses an option that expires before the expected close. The live scenario model does not.
- The resolve clamps at 0.03 and 0.97 make the slope change at 40 percent and 130 percent of the time to close. A smooth curve would need an explicit decision to replace that rule.
- A historical pricing-error study still needs a real option bid, ask, and quote time. This report does not supply them.

## Limits

- The prices are European values from the current functions. They are not exchange quotes and they are not a forecast of profit.
- A difference between the two prices is not evidence that one model is better.
- The anchor probabilities are labels for the sweep. They are not the filing heuristic and they are not a trained probability.
- No paid data source was contacted, and no options file was read.

