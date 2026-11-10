"""Holdout scores for an acquisition probability. A constant score is not a ranking."""


def average_precision(labels, scores):
    positives = sum(labels)
    if not labels or positives == 0:
        return None
    order = sorted(range(len(labels)), key=lambda index: (scores[index], -index), reverse=True)
    hits = 0
    total = 0.0
    for rank, index in enumerate(order, start=1):
        if labels[index]:
            hits += 1
            total += hits / float(rank)
    return total / float(positives)


def roc_auc(labels, scores):
    """Mann-Whitney AUC. Tied scores share a rank, so a constant score is 0.5."""
    if not labels:
        return None
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    order = sorted(zip(scores, labels))
    rank_sum = 0.0
    index = 0
    while index < len(order):
        end = index
        while end < len(order) and order[end][0] == order[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        for cursor in range(index, end):
            if order[cursor][1]:
                rank_sum += average_rank
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / float(positives * negatives)


def brier(labels, scores):
    if not labels or len(labels) != len(scores):
        return None
    return sum((score - label) ** 2 for score, label in zip(scores, labels)) / float(len(labels))


def precision_recall(labels, scores, threshold):
    tp = fp = fn = 0
    for label, score in zip(labels, scores):
        predicted = score >= threshold
        if predicted and label:
            tp += 1
        elif predicted:
            fp += 1
        elif label:
            fn += 1
    return {
        "threshold": threshold,
        "precision": None if tp + fp == 0 else tp / float(tp + fp),
        "recall": None if tp + fn == 0 else tp / float(tp + fn),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def precision_at_k(labels, scores, k):
    if not labels or k <= 0:
        return None
    k = min(int(k), len(labels))
    order = sorted(range(len(labels)), key=lambda index: (-scores[index], index))
    chosen = order[:k]
    return sum(labels[index] for index in chosen) / float(k)


def calibration(labels, scores, bins=5):
    if len(labels) < bins:
        return []
    order = sorted(zip(scores, labels))
    size = len(order) // bins
    rows = []
    for index in range(bins):
        chunk = order[index * size:(index + 1) * size if index < bins - 1 else len(order)]
        if not chunk:
            continue
        rows.append({
            "n": len(chunk),
            "mean_predicted": sum(score for score, _ in chunk) / float(len(chunk)),
            "observed_rate": sum(label for _, label in chunk) / float(len(chunk)),
        })
    return rows


def evaluate(labels, scores, train_rate, top_k=10):
    count = len(labels)
    positives = sum(labels) if labels else 0
    prevalence = None if count == 0 else positives / float(count)
    top_fraction = max(1, int(round(count * 0.05))) if count else 0
    return {
        "rows": count,
        "positives": positives,
        "negatives": count - positives,
        "prevalence": prevalence,
        "pr_auc": average_precision(labels, scores) if scores else None,
        "roc_auc": roc_auc(labels, scores) if scores else None,
        "brier": brier(labels, scores) if scores else None,
        "base_pr_auc": prevalence,
        "base_roc_auc": None if prevalence in (None, 0, 1) else 0.5,
        "base_brier": None if prevalence is None else brier(labels, [train_rate] * count),
        "at_half": precision_recall(labels, scores, 0.5) if scores else None,
        "at_base_rate": precision_recall(labels, scores, train_rate) if scores else None,
        "precision_top_10": precision_at_k(labels, scores, top_k) if scores else None,
        "precision_top_5pct": precision_at_k(labels, scores, top_fraction) if scores else None,
        "top_10": min(top_k, count),
        "top_5pct": top_fraction,
        "calibration": calibration(labels, scores) if scores else [],
    }
