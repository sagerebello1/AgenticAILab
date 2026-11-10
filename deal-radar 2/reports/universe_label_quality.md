# Label quality for a market-wide acquisition test

Generated 2026-11-09.

A positive would be a verified definitive target announcement inside the horizon. A negative would require the horizon to have ended and the announcement record for that company and window to be complete. A phrase search that returned nothing is not that record.

The verified deal table has 749 transactions and 665 companies. 66 companies have more than one verified deal. Unread item 1.01 hits: 8476. Search windows short of EDGAR's reported count: 1581. Because those holes exist, a company-date with no row in the deal table was left unlabeled.

The same rule applied to every quarter-end from 2016 through 2026-11-09, for the 284 stored tickers that map to one CIK:

- 30-day: verified positives 95, censored 0, no price on or before the date 4659, unlabeled 7458, verified negatives 0.
- 60-day: verified positives 152, censored 284, no price on or before the date 4659, unlabeled 7117, verified negatives 0.
- 90-day: verified positives 217, censored 284, no price on or before the date 4659, unlabeled 7052, verified negatives 0.

The 30-day, 60-day, and 90-day counts differ where a verified announcement falls inside the longer window. Those are distinct definitions. They were not turned into a training matrix, because the other company-dates are unlabeled rather than negative.

Censored dates are quarter-ends whose horizon had not ended on 2026-11-09. They were not coded as zero.

Ticker symbols that map to more than one CIK in the snapshots were left out of the grid: 0.
