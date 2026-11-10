"""L2 logistic regression, a random forest, and XGBoost.

Each fit sees the training rows only. Medians used to fill missing values come
from that same training fold. The libraries are the installed scikit-learn and
XGBoost packages. A fold with one class is not fit.
"""
import statistics

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier


def _medians(rows):
    width = len(rows[0])
    medians = []
    for column in range(width):
        observed = [row[column] for row in rows if row[column] is not None]
        medians.append(float(statistics.median(observed)) if observed else 0.0)
    return medians


def _impute(rows, medians):
    filled = [
        [medians[index] if value is None else float(value) for index, value in enumerate(row)]
        for row in rows
    ]
    return np.asarray(filled, dtype=float)


class Fitted:
    def __init__(self, name, family, estimator, columns, medians, mean, std):
        self.name = name
        self.family = family
        self.estimator = estimator
        self.columns = columns
        self.medians = medians
        self.mean = mean
        self.std = std

    def predict(self, rows):
        if not rows:
            return []
        matrix = _impute(rows, self.medians)
        if self.mean is not None:
            matrix = (matrix - self.mean) / self.std
        probabilities = self.estimator.predict_proba(matrix)[:, 1]
        return [float(value) for value in probabilities]

    def importance(self):
        if hasattr(self.estimator, "coef_"):
            weights = self.estimator.coef_[0]
            return [{"feature": name, "weight": float(weight)} for name, weight in zip(self.columns, weights)]
        if hasattr(self.estimator, "feature_importances_"):
            weights = self.estimator.feature_importances_
            return [{"feature": name, "importance": float(weight)} for name, weight in zip(self.columns, weights)]
        return []


def _fit_matrix(rows, labels, scale):
    if len(set(labels)) < 2:
        return None
    medians = _medians(rows)
    matrix = _impute(rows, medians)
    mean = std = None
    if scale:
        mean = matrix.mean(axis=0)
        std = matrix.std(axis=0)
        std = np.where(std < 1e-8, 1.0, std)
        matrix = (matrix - mean) / std
    return medians, matrix, np.asarray(labels, dtype=int), mean, std


def fit_logistic(columns, rows, labels, C):
    prepared = _fit_matrix(rows, labels, scale=True)
    if prepared is None:
        return None
    medians, matrix, target, mean, std = prepared
    estimator = LogisticRegression(C=C, solver="lbfgs", max_iter=1000)
    estimator.fit(matrix, target)
    return Fitted("logistic regression (L2, C=%s)" % C, "logistic", estimator, columns, medians, mean, std)


def fit_forest(columns, rows, labels, depth):
    prepared = _fit_matrix(rows, labels, scale=False)
    if prepared is None:
        return None
    medians, matrix, target, mean, std = prepared
    estimator = RandomForestClassifier(
        n_estimators=200, max_depth=depth, min_samples_leaf=10,
        max_features="sqrt", random_state=7, n_jobs=1,
    )
    estimator.fit(matrix, target)
    return Fitted("random forest (depth %s, 200 trees)" % depth, "random_forest", estimator, columns, medians, mean, std)


def fit_xgboost(columns, rows, labels, depth):
    prepared = _fit_matrix(rows, labels, scale=False)
    if prepared is None:
        return None
    medians, matrix, target, mean, std = prepared
    estimator = XGBClassifier(
        n_estimators=160, max_depth=depth, learning_rate=0.05, reg_lambda=1.0,
        min_child_weight=5, subsample=0.8, colsample_bytree=0.8,
        objective="binary:logistic", eval_metric="logloss",
        random_state=7, n_jobs=1,
    )
    estimator.fit(matrix, target)
    return Fitted("XGBoost (depth %s, 160 trees, lambda 1)" % depth, "xgboost", estimator, columns, medians, mean, std)


def candidates():
    """Small grids. The validation fold picks one setting for each family."""
    return (
        [("logistic", {"C": C}) for C in (0.1, 1.0, 10.0)]
        + [("random_forest", {"depth": depth}) for depth in (3, 5)]
        + [("xgboost", {"depth": depth}) for depth in (2, 3)]
    )


def fit_candidate(family, params, columns, rows, labels):
    if family == "logistic":
        return fit_logistic(columns, rows, labels, params["C"])
    if family == "random_forest":
        return fit_forest(columns, rows, labels, params["depth"])
    if family == "xgboost":
        return fit_xgboost(columns, rows, labels, params["depth"])
    raise ValueError("Unknown model family.")
