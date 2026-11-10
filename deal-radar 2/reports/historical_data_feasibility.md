# Historical data feasibility

Checked 2026-11-10T02:10:56Z. No WRDS session was opened. No schema, table, permission, or date range was returned by WRDS. No model was trained. `black_scholes.py` was not modified, and no probability was connected to option valuation.

An open TCP port is not a database. `wrds-pgdata.wharton.upenn.edu` port 9737 answered at 165.123.60.118, and `wrds-www.wharton.upenn.edu` port 443 answered at 165.123.60.122. This Python is 3.9.6. The packages `wrds`, `psycopg2`, `sqlalchemy`, and `pandas` are not installed. `WRDS_USERNAME` is unset. `~/.pgpass`, `~/.wrds`, and `~/.wrds_credentials` are absent. The project `.env` contains only `EDGAR_USER_AGENT`. No CRSP, Compustat, Capital IQ, or SDC file is in the project.

Because there is no account, `list_libraries()` was not run. Accessible schemas: none. Accessible tables: none. Row counts and vendor date ranges on this account: none.

## Available on disk

These counts were read from `data/historical/ma.sqlite` and the directories beside it. They are the SEC research extract, not a listed-company universe. `data/predictive/representative_universe.json` records that the universe was not built: 0 verified negative company-dates.

| Dataset | What is stored | Coverage |
| --- | --- | --- |
| Verified EDGAR targets | 749 transactions after dropping amendments and same-week duplicates, 665 companies | Announcements 2016-01-05 through 2026-10-13 |
| Deal outcomes from a later filing sentence | 234 closed, 14 terminated, 502 unresolved | Most deals have no close or withdrawal sentence |
| Deal terms | Consideration missing on 594, cash 122, stock 31, mixed 2. Offer price missing on 625. Acquirer name missing on 510 | Extracted when a sentence in the read filing contained it |
| Target snapshots | 2,247 rows, three per deal, at 30, 90, and 180 days before the announcement | 2015-07-09 through 2026-09-13 |
| Phrase-screen companies | 126 companies, one snapshot each | 2021-02-02 through 2024-11-07. The stored outcome is that three merger phrases returned no 8-K |
| Yahoo daily bars | 105,205 bars, 284 symbols | 2014-11-11 through 2026-11-09. Median series length 490 days, the window fetched around a sampled event |
| Price requests that returned nothing usable | 174 with no Yahoo listing, 52 whose current listing starts after the historical date, 3 with no bars | Those series were not filled in |
| SEC submissions and company facts | 792 submission files, 252 fact files | Companies already in this extract |
| News | 0 rows in `historical_news_signals`. One GDELT day, 2021-02-03, in the bulk pilot | Not a history of coverage |

EDGAR search itself is incomplete relative to a census: 3,829 filings were read out of 25,935 stored hits, 8,476 item 1.01 hits are unread, and 1,581 search windows saved fewer pages than EDGAR reported.

The earlier case-control XGBoost fit is unchanged and is not a market-wide test. Its reports remain in `reports/acquisition_oos_evaluation.md` and `reports/universe_oos_evaluation.md`.

## WRDS products required, and what this account can see

CRSP, Compustat, S&P Capital IQ, and LSEG SDC Platinum are separate licenses inside a WRDS subscription. A future login does not imply all four. The only confirmation is `list_libraries()` after that login. None of the following schemas were listed here.

| Need | Documented WRDS location | Seen on this account |
| --- | --- | --- |
| Daily prices, volumes, returns, and the CUSIP on that row | `crsp.dsf` (legacy daily file) or the current daily file the library list names | No |
| Historical ticker, name, and CUSIP, with start and end dates | `crsp.dsenames` | No |
| Delisting date, code, and delisting return | `crsp.dsedelist`, or the delisting table the current CRSP file uses | No |
| Permanent security and company ids | `permno` and `permco` on the CRSP name file | No |
| Link from CRSP to Compustat for a date | `crsp.ccmxpf_lnkhist` (`linkdt`, `linkenddt`) | No |
| Quarterly and annual financial statements | `comp.fundq`, `comp.funda` | No |
| Compustat company header, including CIK when S&P filled it | `comp.company` | No |
| SDC M&A announcements, withdrawals, and consideration | `tr_sdc_ma.wrds_ma_details` | No |
| Capital IQ, if the subscription includes it | A `ciq` schema is a different product from SDC. Its deal tables, if any, have to be read from the library list | No |
| CIK to CUSIP bridge some accounts have | `wrdssec.wciklink_cusip` | No |

WRDS publishes CRSP daily coverage as beginning 1925-12-31 for NYSE, 1962-07-02 for AMEX, 1972-12-14 for NASDAQ, and 2006-03-08 for NYSE Arca, in the CRSP Data Descriptions Guide on wrds-www. That is a vendor description of the product. It is not the end date or the row count on this account. Compustat’s US and Canadian annual history is described in public research notes as beginning in 1950, with quarterly history from 1962. That description was not checked with a query. SDC’s begin date, end date, and deal count were not returned.

Expected record counts for those tables are unknown until a licensed session runs `count(*)`, `min(date)`, and `max(date)` on each table the library list actually contains. No outside estimate is used here.

## Specification

The universe is one row per listed company per prediction date. A company that later delists stays in the dates when it was listed.

**Membership.** A security is in the universe on a date when the CRSP name range covers that date and the share and exchange codes are the common-stock universe chosen in advance (ordinary common shares on NYSE, AMEX, NASDAQ, and, if included, NYSE Arca). Membership comes from the name history, not from today’s ticker list and not from a Yahoo chart.

**Identifiers.** Keep `permno` as the security id and `permco` as the company id. Carry `gvkey` only through a CCM link valid on that date. Carry CIK when Compustat or the SEC bridge has it. Store the CUSIP, ticker, and company name that were current on that date, each with its own start and end. A later ticker change does not rewrite the old row.

**Prices and volume.** Daily close, return, and volume from the CRSP daily file, for dates on or before the prediction date. A missing return stays missing. The series has to include companies that later leave the exchange.

**Delisting.** Delisting date, delisting code, and delisting return are outcomes after the last trade. They are not features on a prediction date before the delisting. If the stock disappears inside an outcome window, the delisting return is the outcome and later closes stay empty.

**Financial statements.** Quarterly and annual revenue, assets, cash, debt, equity, and shares. The usable date is the report date (`rdq` for a quarter), not the period end. A March quarter reported in May is absent from an April snapshot. Compustat’s standard filters (`indfmt`, `datafmt`, `popsrc`, `consol`) have to be fixed before any count, because omitting them duplicates firm-years.

**Announcements.** A positive label is a verified definitive announcement whose announcement date falls inside the horizon. Sources are SDC, when licensed, and the EDGAR filings already read. SDC status in a current vintage is the latest status, not the status known on the announcement day. Completion date, withdrawal date, and final status are labels for a later question. They are not inputs to a pre-announcement feature.

**Failed and withdrawn deals.** Withdrawn and terminated deals stay in the announcement file. They are positives for “an announcement happened.” They are negatives for “the announced deal closed.” Unresolved deals stay unresolved. They are not recoded as closed or as withdrawn.

**Consideration.** Cash, stock, or mixed, plus the stated price per share and the exchange ratio when the source records them. A missing term stays missing. EDGAR already leaves consideration empty on 594 of 749 verified targets and the offer empty on 625.

**Labels.** For each horizon of 30, 60, and 90 days, the label is 1 when a verified announcement falls in that window. The label is 0 only when the window has ended and the announcement record for that window is complete enough to support the zero. A missing SDC row, or an EDGAR phrase that did not hit, is not a zero. A window that has not ended is censored, not zero. The three horizons are separate. A 60-day label is not a copy of the 30-day label.

## Historical joins

Join on a permanent id and a date. The current ticker and the current company name are display fields.

1. Start from the CRSP name record whose `namedt` / `nameendt` contains the prediction date. That supplies `permno`, `permco`, the historical ticker, and the historical CUSIP.
2. Attach daily prices where `permno` and the price date match, and the price date is on or before the prediction date.
3. Attach Compustat through `crsp.ccmxpf_lnkhist` only when the prediction date is between `linkdt` and `linkenddt`. Prefer confirmed primary links (`linktype` LC or LU, and `linkprim` P or C). Another link type is stored and flagged, not treated as the same security.
4. Attach a financial statement only when its report date is on or before the prediction date.
5. Attach an EDGAR filing by CIK. Compustat `company.cik` is one bridge, used when it is filled. `wrdssec.wciklink_cusip` is another, used only if the library list includes it. The historical CUSIP on the announcement date is the fallback. Compustat CUSIPs are often nine characters and CRSP CUSIPs are eight. Compare the eight-character issuer CUSIP, not the raw strings.
6. Attach an SDC deal by the target CUSIP on the announcement date, then to `permno` through the CRSP name record for that date. Match the acquirer the same way when the acquirer is public. A deal with no `permno` stays in the deal table with a null id.
7. Corporate actions stay on the CRSP distribution and delisting records for that `permno`. They are not reconstructed by assuming today’s ticker was always the same company.

An unmatched EDGAR target stays unmatched. It is not assigned a nearby name or a reused ticker.

## Data-quality concerns

- The SEC deal list is the part of a phrase search that was read. It is not every announcement since 2016.
- The 126 phrase-screen companies are not verified non-targets, and they are not a market draw.
- Yahoo’s 284 series miss delisted names and stop at the window that was requested. A symbol that now belongs to a different company was already rejected when the listing start date was after the historical date.
- SDC, once licensed, will still be a current vintage. Announcement research can use the announcement date. It cannot use the latest status as if that status were known that day.
- Compustat restates history. A snapshot has to respect the report date, and a later restatement is a known look-ahead risk to audit after the files arrive.
- The same company can have more than one `permno` over time. The CCM link is date-bounded for that reason. Joining on CUSIP alone will cross corporate actions.
- GDELT does not fill this gap. The bulk pilot is one UTC day.

## Exact next steps

1. Get a WRDS username from the institution that holds the subscription. The EDGAR contact address does not create that account. Put the password only in `~/.pgpass` as one line, mode 600: `wrds-pgdata.wharton.upenn.edu:9737:wrds:USERNAME:PASSWORD`. Do not commit it.
2. Install the `wrds` client in this Python. The first remote session often requires Duo.
3. Run `list_libraries()` and save the names. Stop if `crsp` is absent. Record whether `comp`, `tr_sdc_ma`, and any Capital IQ schema are present or absent. Do not query a schema that is not listed.
4. On each listed table, save the row count, the minimum date, the maximum date, and the share of nulls in `permno`, `permco`, CUSIP, ticker, announcement date, withdrawal date, consideration, and the statement report date. Those are the first real record counts.
5. Import into new tables beside `data/historical/ma.sqlite`. Leave the EDGAR rows, the Yahoo bars, and the existing experiment files as they are. Keep the vendor files out of git.
6. Match the 749 verified targets to a `permno` on the announcement date and write the match rate. Leave unmatched rows unmatched. Repeat the match for the 126 phrase-screen companies without calling them confirmed non-targets.
7. Build prediction-date membership from the CRSP name ranges. Label a company-date as a positive only from a verified announcement inside 30, 60, or 90 days. Leave every other company-date unlabeled until the SDC-versus-EDGAR overlap is measured and the report says which zeros are supported.
8. Train only after that label file exists, with a chronological split and a calibration period that is not the final holdout. Until then the valuation module receives no probability from this work.

The earlier access note is `reports/wrds_access_integration.md`. This check reaches the same conclusion: nothing from CRSP, Compustat, Capital IQ, or SDC is available to count or join.
