# GDELT bulk pilot

Checked 2026-11-09T23:48:27Z. The DOC search API was not called. No production score was changed.

## Archive

GDELT 2.0 publishes three files every 15 minutes. `lastupdate.txt` lists the newest export, mentions, and GKG zip. `masterfilelist.txt` is the historical index, 129,349,356 bytes on this check. It was streamed and not stored. Each index line is a size, an MD5, and a URL.

The pilot uses the GKG files only. GKG carries the source, the article URL, organization names, themes, and tone. The pilot day is 3 February 2021 UTC, because that day falls on or before the stored prediction dates for a group of SEC companies and is small enough to keep. The 96 files for that day are about 717MB compressed. A 7-day or 90-day archive was not downloaded.

File status: verified=96.

GKG rows scanned: 173460. Rows too short to parse: 1. Duplicate company-article rows dropped: 0.

## Companies

The pilot uses companies already in the SEC tables. In-window companies have a prediction date on or after 3 February 2021, so this day's processing time is allowed. Before-cutoff companies have a prediction date of 1 or 2 February, so the same files are after their cutoff.

Matched mention rows: 4278. Companies with at least one matched URL: 6.

- Aegion Corp (None), target, snapshot 2021-01-18, label 1, mentions None, sources None, tone None, acquisition themes None, reason archive_after_cutoff, discarded after cutoff 0
- CENTENE CORP (CNC), target, snapshot 2021-01-18, label 1, mentions None, sources None, tone None, acquisition themes None, reason archive_after_cutoff, discarded after cutoff 5
- UNITIL CORP (UTL), non_acquired, snapshot 2021-02-02, label 0, mentions None, sources None, tone None, acquisition themes None, reason archive_after_cutoff, discarded after cutoff 2
- AMAZON COM INC (AMZN), non_acquired, snapshot 2021-02-03, label 0, mentions 1339, sources 706, tone 1.081, acquisition themes 0, reason observed, discarded after cutoff 0
- Alphabet Inc. (GOOG), non_acquired, snapshot 2021-02-03, label 0, mentions 2887, sources 1250, tone 0.139, acquisition themes 0, reason observed, discarded after cutoff 0
- CoreSite Realty Corp (None), non_acquired, snapshot 2021-02-05, label 0, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- Otis Worldwide Corp (OTIS), non_acquired, snapshot 2021-02-05, label 0, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- PayPal Holdings, Inc. (PYPL), non_acquired, snapshot 2021-02-05, label 0, mentions 40, sources 18, tone 0.963, acquisition themes 0, reason observed, discarded after cutoff 0
- UNION CARBIDE CORP /NEW/ (None), non_acquired, snapshot 2021-02-05, label 0, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- Apollo Global Management, Inc. (APO), target, snapshot 2021-02-06, label 1, mentions 5, sources 5, tone 2.023, acquisition themes 0, reason observed, discarded after cutoff 0
- Pluralsight, Inc. (PS), target, snapshot 2021-02-06, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- WSFS FINANCIAL CORP (WSFS), target, snapshot 2021-02-08, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- PLUMAS BANCORP (PLBC), target, snapshot 2021-02-09, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- Wheeler Real Estate Investment Trust, Inc. (WHLR), target, snapshot 2021-02-10, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- Aegion Corp (None), target, snapshot 2021-02-13, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- GenMark Diagnostics, Inc. (GNMK), target, snapshot 2021-02-13, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0
- Extended Stay America, Inc. (STAY), target, snapshot 2021-02-14, label 1, mentions 0, sources 0, tone None, acquisition themes 0, reason observed, discarded after cutoff 0

## What was joined

Each mention is stored with the SEC CIK and the prediction date. The raw zips stay in `data/historical/gdelt_bulk/raw`. The company rows, matches, and features are in `data/historical/gdelt_bulk/pilot.sqlite`. A mention is not a probability.

Rolling 7-day, 30-day, and 90-day changes are empty for every company. Those windows include days that were not downloaded. The empty value is missing coverage, not a change of zero.
