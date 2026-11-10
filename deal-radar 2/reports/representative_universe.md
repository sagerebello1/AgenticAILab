# Representative historical universe

Generated 2026-11-09.

The universe was not constructed. `data/predictive/representative_universe.json` records that decision and contains no labeled company-dates.

## What a usable universe would need

- The companies listed on each prediction date, including names that later delisted or were acquired.
- A price on or before that date for each of those companies.
- Every definitive acquisition announcement, so a finished window with no announcement can be labeled zero.

## What is stored

- 749 verified target transactions, from the portion of the EDGAR phrase search that was read.
- 126 companies labeled non-acquired because three merger phrases returned no 8-K. That draw is 16 one-week slices of 10-K filers in 2021–2024, skipping companies already marked as targets.
- Yahoo bars for 284 symbols, each covering roughly the 420 days before a sampled event and up to 70 days after it. Median stored span: 490 days.
- 174 symbols with no Yahoo listing and 52 whose current Yahoo listing starts after the historical date. Those bars were not invented.
- 792 SEC submission files and 252 company-facts files for companies already in this extract.
- No historical exchange membership, CRSP name history, or full-market ticker file.

Quarter-end dates from 2016 were checked against the stored bars. Company-dates with a price and a verified announcement inside the horizon were counted as positives. Every other finished company-date stayed unlabeled. Verified negatives written: 0.

Filling the unlabeled dates with zero, or copying the case-control sample forward, would manufacture the observations this check is supposed to test.
