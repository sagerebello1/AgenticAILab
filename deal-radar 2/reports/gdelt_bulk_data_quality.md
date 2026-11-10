# GDELT bulk data quality

## Coverage

Files in the 3 February 2021 GKG index: 96.
Verified files match the index size and MD5. A download that fails, including HTTP 429, is not retried when the status is 429. A server error can be retried up to three times with exponential backoff and jitter. A failed slot is recorded and is not read as an empty news file.

Failed or unverified files:
None.

## Timestamps

GKG `DATE` is the 15-minute time GDELT processed the file. It is stored as the observation time. The file has a `Dates` column of dates mentioned in the text, and some URLs contain a path date. Neither is stored as the publisher's publication time. Mention rows with a publication time: 0 of 4278.

## Matches

Organization names come from the GKG organization fields. A cleaned SEC name or a listed alias must appear as consecutive tokens. Alphabet also matches Google. A ticker matches only when it is the entire organization name, so OTIS does not match Otis Technology. One article URL is stored once per company. A second 15-minute copy of the same URL is dropped.

Rows scanned: 173460. Short rows: 1. Duplicate mention rows dropped: 0. Mention rows kept: 4278.

## Missing versus zero

Companies with a complete archive day on or before the prediction date: 14. Of those, explicit zero mentions: 10.
Companies whose prediction date is before the archive day: 3. Their mention count is empty. Matched articles discarded because the observation time is after the prediction date: 7.
Companies left empty because the archive day is incomplete: 0.

A zero appears only when every indexed file for the day verified and the company had no matching organization.
