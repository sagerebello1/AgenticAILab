# GDELT feature report

These features are computed only from GDELT buckets on or before the prediction date.

## Definitions

- `mentions_7`, `mentions_30`, `mentions_90`: sum of daily article counts. A day the timeline did not return makes the sum missing.
- `change_7`, `change_30`, `change_90`: the recent sum minus the sum of the immediately previous window of the same length. The 30-day change needs 60 observed days.
- `tone_7`, `tone_30`, `tone_90`: mean of the daily average tones GDELT returned. A day without a tone is skipped. If every day in the window lacks a tone, the mean is missing. Tone is not filled with zero.
- `keywords_30` and `keyword_change_30`: the same sums for articles matching the company and one fixed keyword clause: strategic review, strategic alternatives, potential sale, activist investor, takeover interest, merger rumor, acquisition, merger, or takeover.
- The separate themes were not given separate API calls. One extra call per theme would have multiplied the request count. The keyword feature is the combined count, not five independent frequencies.

Observed 30-day mention rows: 0. Explicit zeros among them: 0.

## Missing and present

- mentions_7: 140 missing, 0 present
- mentions_30: 140 missing, 0 present
- mentions_90: 140 missing, 0 present
- change_7: 140 missing, 0 present
- change_30: 140 missing, 0 present
- change_90: 140 missing, 0 present
- tone_30: 140 missing, 0 present
- keywords_30: 140 missing, 0 present
- keyword_change_30: 140 missing, 0 present

## Highest observed 30-day mention counts

- None.

A high count is not a finding that the company was about to be acquired. Common names and large companies generate coverage for other reasons. The query string is stored on each request so a match can be checked.
