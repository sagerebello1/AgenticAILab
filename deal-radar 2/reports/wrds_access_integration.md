# WRDS access and integration report

Checked 2026-11-09. No WRDS data was imported. No model was trained. Production DealRadar scoring was not changed.

## What this machine can reach

| Check | Result |
|---|---|
| `wrds`, `psycopg2`, `sqlalchemy`, `pandas` | Not installed |
| `WRDS_USERNAME` or any CRSP, Compustat, SDC, or LSEG variable | Not set |
| `~/.pgpass` or `~/.wrds` | Not present |
| Local CRSP, Compustat, or SDC files in the project or home directory | None |
| `wrds-pgdata.wharton.upenn.edu` port 9737 | Host resolves and the TCP port is open |
| `wrds-www.wharton.upenn.edu` port 443 | Host resolves and the TCP port is open |
| Python | 3.9.12, which is inside the `wrds` package's supported 3.8–3.12 range |

An open port is not a login. WRDS did not return a library list, a row count, or a table. Nothing from SDC, CRSP, or Compustat is on disk, so the measured improvement over the SEC dataset is zero.

## How access actually works

WRDS is an institutional subscription. CRSP, Compustat, and LSEG SDC are separate products inside that subscription. A login does not imply all three are licensed. The only way to know which ones an account can read is `list_libraries()` after that account connects.

There is no public API key for these datasets. The supported paths are:

1. A WRDS account, registered with an institutional email and approved by that institution. Faculty, doctoral, and some master's or class accounts are the usual cases. A personal Gmail address does not create an account.
2. The website at `https://wrds-www.wharton.upenn.edu`. Small queries can be downloaded as CSV, Stata, or SAS. Those files are the import DealRadar can use without installing the database client.
3. PostgreSQL at `wrds-pgdata.wharton.upenn.edu`, port `9737`, database `wrds`, with TLS. The password belongs in `~/.pgpass` as one line, mode `600`:

   `wrds-pgdata.wharton.upenn.edu:9737:wrds:USERNAME:PASSWORD`

   The Python package is `wrds`. The first remote session can require Duo. The username can sit in `WRDS_USERNAME`. The password must not sit in the repository or in source code.
4. WRDS Cloud over SSH, for people whose institution uses that route. This machine is not logged into it.

Day-pass web access, where a school offers it, can download files. It is not the same as a programming login.

LSEG Workspace is a different product from the WRDS SDC tables. It was not installed or called.

## What each product would supply, once a license is confirmed

Schema names below are the names documented for WRDS PostgreSQL. They have not been listed on this account. If `list_libraries()` does not show a schema, that product is missing and must stay missing.

### LSEG SDC Platinum

Documented WRDS schema: `tr_sdc_ma`. Documented deals table: `wrds_ma_details`.

This is the source for the deal itself: target and acquirer names, CUSIPs, tickers, announcement date, completion date, withdrawal date, deal value, price per share, consideration, public or private status, and status such as completed, pending, or withdrawn.

SDC extracts are a current vintage. The status column is the latest status WRDS has, not the status a researcher would have seen on the announcement date. Final status, completion date, and withdrawal date are labels for the closing model. They are not features in the pre-announcement model.

### CRSP

Documented schema: `crsp`.

| Table | Use |
|---|---|
| `dsf` | Daily price, return, volume, and the CUSIP on that row. Permanent id is `permno`. |
| `dsenames` | Historical ticker, CUSIP, and name, with `namedt` and `nameendt`. This is the ticker map. The current ticker is not. |
| `dsedelist` | Delisting date, delisting code, and delisting return. |
| `ccmxpf_lnkhist` | CRSP `permno` to Compustat `gvkey`, valid only between `linkdt` and `linkenddt`. |

CRSP keeps companies after they leave the exchange. That is the gap Yahoo does not fill: of 513 symbols requested from Yahoo, 284 returned a bar, 174 were absent, and 52 now belong to a later listing. A delisting return is an outcome after the last trade. It does not fill prices from before the announcement.

### Compustat

Documented schema: `comp`.

| Table | Use |
|---|---|
| `fundq` | Quarterly revenue, assets, debt, cash, equity, shares, and income. `gvkey` plus `datadate` identifies the quarter. |
| `funda` | Annual statements and historical SIC. |
| `company` | Header fields, including CIK where S&P populated it. |

`datadate` is the period end. `rdq` is the report date. A March quarter reported in May is not known in April. A snapshot may use a row only when `rdq` is on or before the prediction date. Quarter-end price `prccq` is not a daily CRSP price and is not known before the report date.

## How the files would join the SEC dataset

The SEC tables stay where they are: `data/historical/ma.sqlite`. WRDS rows would land in new tables beside them. A WRDS row never overwrites an EDGAR accession, an extracted sentence, or a price that Yahoo actually returned.

The join order, and only when the date falls inside the link:

1. EDGAR CIK on the filing.
2. Compustat `company.cik`, when it is filled, to `gvkey`.
3. If CIK is empty, CRSP `dsenames` matches the historical ticker and CUSIP on the announcement date, not today's ticker.
4. `crsp.ccmxpf_lnkhist` maps `gvkey` to `permno` for that date. Preferred links are the confirmed primary types (`LC` or `LU`, primacy `P` or `C`). An unconfirmed or secondary link is stored and flagged, not treated as certain.
5. SDC's target CUSIP joins to the CRSP CUSIP on the announcement date. Compustat CUSIPs are often nine characters and CRSP CUSIPs are eight. They are not compared as raw strings.
6. WRDS also distributes `wrdssec.wciklink_cusip` on some accounts. That is a CIK-to-CUSIP bridge. It is usable only if the account's library list includes it.

Unmatched deals stay in the SEC table with a null `permno`. They are not assigned a nearby name.

## Three datasets, still unbuilt

No rows were written for these. They are the shapes to build after the files arrive.

**Acquisition, before the announcement.** One row per company and prediction date. The label is an SDC or EDGAR announcement inside 30, 90, or 180 days. Features may include CRSP returns, volume, and volatility from dates before the prediction date, and Compustat figures with `rdq` on or before that date. Industry deal counts may include only deals announced before that date. The prediction row may not include the offer, the consideration, the deal value, the announcement return, the delisting return, or the final SDC status.

**Post-announcement traded price.** One row per announced deal. Features known on the announcement date: the pre-announcement CRSP close, the SDC offer and consideration if SDC records them as announcement terms, size, and the market return. Outcomes are CRSP closes one session before the announcement and on the announcement session, then 1, 5, 10, and 30 sessions later. If the stock delists inside that window, the delisting return is the outcome and the missing later closes stay missing.

**Announced-deal completion.** One row per announced deal. The label is completed, withdrawn, or still unresolved, using SDC dates when present and the EDGAR sentence when that is all we have. Features are terms known at announcement. A later SDC status revision is a label, not an announcement-day feature. Deals with no completion date and no withdrawal date stay unresolved. They are not marked completed.

Controls are CRSP companies with no SDC or EDGAR announcement inside the horizon. The horizon has to have ended. A missing SDC row is not proof that no deal existed, so the report has to show how many EDGAR targets SDC did not contain.

## Quality checks required before any training

Training stays off until every line below is measured on the imported files and written into a data report.

- `list_libraries()` shows `crsp`, `comp`, and `tr_sdc_ma`, or the report names which of the three are absent.
- Each imported table has a row count, a date range, and a share of nulls for the fields the model would use.
- Match rate from the existing 749 EDGAR targets to a `permno`, and the same rate for the 126 non-acquired companies.
- Duplicate SDC deal numbers are one deal. Same-week EDGAR duplicates stay collapsed.
- A look-ahead audit finds zero pre-announcement features with a CRSP date, Compustat `rdq`, or SDC announcement after the prediction date.
- Delisted `permno`s are counted separately from live ones. Their missing pre-announcement prices are not filled.
- Unresolved SDC outcomes are counted and are not recoded as completed.
- The chronological split is possible on the imported date range. Random mixing of years is not a pass.
- Only after that: logistic regression against the historical base rate, then a tree model if the sample passes. Metrics are precision, recall, PR-AUC, Brier score, and a calibration table, with the sample size of each split. Those numbers are not estimated here.

Raw CRSP, Compustat, and SDC files are licensed. They stay out of git. Derived match rates can be reported. The vendor rows cannot.

## What is still missing, and what would change

Today's SEC set, from `reports/historical_data_readiness.md`, is unchanged by this check:

- 749 verified targets, 126 non-acquired companies, 8,476 unread EDGAR hits.
- 501 of 749 deals have no completion or termination sentence.
- 237 deals have a before-and-after market close. Seven also have a cash offer.
- 288 targets have no ticker, so Yahoo was never asked. Another 226 asked symbols returned nothing or belong to a later listing.
- Compustat-style statements were retrieved for 252 companies, from SEC companyfacts, and only when the filed date was early enough.

SDC would be the source for offer, consideration, value, acquirer identity, and completed-versus-withdrawn status, which are the fields most often empty in the SEC extract. CRSP would be the source for delisted prices and a stable security id. Compustat would be the source for statements of companies that no longer file, dated by the report date rather than the period end.

None of that improvement has been measured, because none of the three files could be opened.
