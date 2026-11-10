# GDELT bulk model comparison

The prediction date is the SEC snapshot: 30 days before a verified announcement, or the stored date for a company that was not acquired. The label is an announcement inside the next 30 days. News features may use only GKG rows processed on or before that date.

Pilot companies with an observed mention count: 14. Positives: 8. Negatives: 6. A 30 percent holdout would be 4 rows. Companies that also have a SEC price or a SEC statement on the snapshot: 13.

## Result

The comparison was not scored. The pilot does not clear the existing acquisition gate (rows, positives, negatives, holdout). No model was fit. SEC-only and SEC-plus-GDELT probabilities were not produced. The bulk archive was downloaded, parsed, and joined. That is not evidence that the news features improve a forecast.

The gate is 100 rows, 20 positives, 20 negatives, and 15 holdout rows. The 7-day, 30-day, and 90-day coverage changes are also missing, because only one UTC day was downloaded.
