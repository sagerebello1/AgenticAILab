# News model comparison

Prediction date: 30 days before a verified SEC announcement, or the stored snapshot for a non-acquired company. The label is an announcement inside the next 30 days. Training uses the earlier snapshots. The test uses the later snapshots. The split is chronological, not random.

The sample is the companies whose GDELT 30-day mention count was fully observed and that already have a SEC price or a SEC statement on that date. It is a case-control extract of the existing SEC file, not a draw of every public company.

Rows: 0. Positives: 0. Negatives: 0. Holdout: 0.

## Result

The comparison was not scored. The paired sample does not clear the existing acquisition gate (rows, positives, negatives, holdout). No logistic model was fit. No probability was saved. News features are not an improvement over the SEC fields, because that comparison was not run.

The gate is 100 rows, 20 positives, 20 negatives, and 15 holdout rows, with both classes on each side of the date split. Lowering it would not make this sample evidence.
