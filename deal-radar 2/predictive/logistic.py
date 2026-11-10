"""A small logistic regression used only when a dataset clears the sample gates.

The live app does not call this. A fit on a handful of deals is not saved.
"""
import math


def _sigmoid(z):
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def fit(rows, labels, steps=400, learning_rate=0.2):
    """Fit an intercept plus one weight per column. rows are equal-length lists."""
    if len(rows) != len(labels) or not rows:
        raise ValueError("Rows and labels must be the same non-empty length.")
    width = len(rows[0]) + 1
    weights = [0.0] * width
    for _ in range(steps):
        gradient = [0.0] * width
        for row, label in zip(rows, labels):
            score = weights[0] + sum(weight * value for weight, value in zip(weights[1:], row))
            error = _sigmoid(score) - float(label)
            gradient[0] += error
            for index, value in enumerate(row):
                gradient[index + 1] += error * value
        scale = learning_rate / len(rows)
        weights = [weight - scale * grad for weight, grad in zip(weights, gradient)]
    return weights


def probability(weights, row):
    score = weights[0] + sum(weight * value for weight, value in zip(weights[1:], row))
    return _sigmoid(score)
