# GDELT data readiness

Checked 2026-11-09T23:16:29Z. No production score was changed. No probability was written into DealRadar.

## What can be retrieved

GDELT's DOC 2.0 API is the historical search that this machine can call without a subscription. Its documented full-text window now starts on 1 January 2017. Timeline volume, raw article counts, and average tone accept a start and end inside that window. The API asks for one request every five seconds. A burst is answered with HTTP 429 and no data.

The calls used here are `timelinevolraw` for mention counts, `timelinetone` for average tone, and `timelinevolraw` again for a fixed acquisition-keyword query. English-language coverage only (`sourcelang:english`). Each query is the cleaned SEC name, plus a ticker of at least three letters when that ticker is not a common word. A one-word generic name is not queried.

February 2015 through December 2016 is the start of the GDELT 2.0 15-minute files, not of this API. Those files were not downloaded. The disk had about 350MB free, and the 15-minute archive is hundreds of thousands of files. The June 2026 web-ngram feed is a current minute-by-minute histogram, not a backfile to 2015. It was not used as historical news.

Probe notes: A 1-20 August 2017 timelinevolraw query for "GoPro" returned HTTP 200, daily article counts, and the count of all articles GDELT monitored that day. All 20 days were present. A 1-8 August 2017 timelinetone query returned hourly average tone, including hours with tone 0. A 19 February 2015 timelinevolraw query returned HTTP 200 and the text "Invalid query start date." The 15-minute file 20150218230000.gkg.csv.zip is 10,768,507 bytes and was not downloaded. The web-ngram file for 1 January 2017 returned HTTP 404. A 30 June 2026 ngram minute file is 8,192,280 bytes and was not downloaded. Calls made close together returned HTTP 429 and no rows.

## What was stored

Companies considered: 140.

Identity:
- identity_status=ambiguous, n=7
- identity_status=queryable, n=133

Requests:
- series=keywords, http_status=429, n=1
- series=mentions, http_status=429, n=1
- series=tone, http_status=429, n=1

Feature coverage:
- coverage=ambiguous, kind=non_acquired, label=0, n=5
- coverage=ambiguous, kind=target, label=1, n=2
- coverage=not_retrieved, kind=non_acquired, label=0, n=40
- coverage=not_retrieved, kind=target, label=1, n=92
- coverage=request_failed, kind=non_acquired, label=0, n=1

Rows with a complete 30-day mention count: 0. Of those, explicit zeros: 0. A company that was not queried, a failed request, and a day the timeline did not return are missing. They are not coded as zero.

Timeline buckets dated after the prediction snapshot and still stored: 0. Features ignore any such bucket.

Article rows stored: 0. Rows with a publisher timestamp distinct from GDELT's observation time: 0. The timeline buckets are GDELT's observation time. The DOC article list's `seendate` is also an observation time. This pull did not receive a separate publication timestamp, so none was invented.

## Join

News rows carry the SEC CIK and the prediction date. Targets use the date 30 days before the announcement. Non-acquired companies use the snapshot already stored in the SEC table. The label is whether an announcement falls in the next 30 days. A horizon that has not ended is left blank. Companies with no SEC price and no SEC statement on that date were not sent to GDELT.

The SEC filing text, offer, and the announcement itself are not news features.

## Improvement

A complete mention history was observed for 0 company-dates. Whether that changes a forecast is in `reports/news_model_comparison.md`. Coverage this small, or a sample that fails the existing size gate, is not evidence that news predicts acquisitions.
