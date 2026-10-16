"""Step 3: train and test the close-probability model.

    python3 training/train.py                 # train on data/ built by collect.py and label.py
    python3 training/train.py --demo          # smoke test on SYNTHETIC data, writes data/model.demo.json only

What it does
  * turns every labelled announcement into features (features.py)
  * splits by DATE: oldest 70% to fit, next 15% to choose the regularisation, newest 15% to test.
    A random split would let the model peek at the future, so it is not used.
  * compares the model on the test set against two baselines: always predicting the historical
    close rate, and the hand-written rules in terms.py that Deal Radar used before training
  * reports Brier score, log loss, AUC and a calibration table, because the number that matters
    for pricing an option is whether "90%" really means 9 in 10
  * refits on all data and writes data/model.json, which server.py loads automatically
  * fits deal timing curves (how long deals take to resolve) used for "decided before expiry"
"""
import argparse
import json
import math
import os
import random
import sys
from datetime import date, datetime

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from common import data_dir, read_gz, read_jsonl
import features as F
import terms

C_GRID = [0.03, 0.1, 0.3, 1.0, 3.0]
GRID_DAYS = list(range(0, 541, 30))


# ---------- data ----------
def load_real(role):
    labels = read_jsonl(os.path.join(data_dir(), "labels.jsonl"))
    rows = []
    for r in labels:
        path = os.path.join(data_dir("text"), r["adsh"] + ".txt.gz")
        if not os.path.exists(path):
            continue
        feats, t = F.vectorize(read_gz(path), r.get("sic"))
        is_target = F.filer_is_target(r["filer"], t)
        if role == "target" and is_target is False:
            continue
        rows.append({"x": feats, "y": r["label"], "date": r["filedOn"], "days": r["days"]})
    return rows


def make_demo(n=3000, seed=7):
    """Synthetic deals drawn from a made-up rule. Only proves the code runs; says nothing about real deals."""
    rnd = random.Random(seed)
    true = {"second_request": -1.2, "n_foreign": -0.5, "fin_cond": -0.9, "tender": 0.6, "spac": -1.6, "no_fin_cond": 0.3,
            "going_private": -0.3, "voting_agreement": 0.5, "stock": -0.2}
    rows = []
    for i in range(n):
        x = dict.fromkeys(F.FEATURES, 0.0)
        for k in ("hsr", "tender", "vote", "go_shop", "term_fee", "reverse_fee", "going_private", "voting_agreement", "appraisal"):
            x[k] = float(rnd.random() < 0.4)
        x["spac"] = float(rnd.random() < 0.08)
        x["second_request"] = float(rnd.random() < 0.1)
        x["fin_cond"] = float(rnd.random() < 0.15)
        x["no_fin_cond"] = float(not x["fin_cond"] and rnd.random() < 0.5)
        x["n_foreign"] = float(rnd.choice([0, 0, 0, 1, 2]))
        c = rnd.choice(["cash", "cash", "stock", "mixed"])
        x[c] = 1.0
        x["log_len"] = rnd.uniform(3.5, 5.3)
        x["sic_" + rnd.choice([n for n, _, _ in F.SIC_DIVISIONS])] = 1.0
        z = 2.8 + sum(true.get(k, 0) * v for k, v in x.items()) + rnd.gauss(0, 0.4)
        y = int(rnd.random() < 1 / (1 + math.exp(-z)))
        d = date.fromordinal(date(2005, 1, 1).toordinal() + int(i * (7600 / n)))
        days = int(min(540, rnd.lognormvariate(4.6 if x["tender"] else 5.2, 0.5)))
        rows.append({"x": x, "y": y, "date": d.isoformat(), "days": days})
    return rows


# ---------- metrics ----------
def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def rules_prob(x):
    flags = {"hsr": x["hsr"] > 0, "secondRequest": x["second_request"] > 0, "foreign": ["f"] * int(x["n_foreign"]),
             "other": ["o"] * int(x["n_other"]), "financingCondition": True if x["fin_cond"] else False if x["no_fin_cond"] else None,
             "tender": x["tender"] > 0, "vote": x["vote"] > 0, "goShop": x["go_shop"] > 0}
    cons = "stock" if x["stock"] else "cash"
    return terms.estimate_probabilities(cons, flags)[0]


def metrics(y, p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    out = {"n": int(len(y)), "close_rate": float(np.mean(y)), "brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1]))}
    out["auc"] = float(roc_auc_score(y, p)) if len(set(y)) > 1 else None
    bins, rows = [0, 0.5, 0.8, 0.9, 0.95, 1.0001], []
    for a, b in zip(bins, bins[1:]):
        m = (p >= a) & (p < b)
        if m.sum():
            rows.append({"range": "%.2f-%.2f" % (a, min(b, 1)), "n": int(m.sum()), "mean_pred": float(p[m].mean()), "actual": float(np.mean(np.asarray(y)[m]))})
    out["calibration"] = rows
    return out


# ---------- timing ----------
def group_of(x):
    return "tender" if x["tender"] else "second_request" if x["second_request"] else "vote" if x["vote"] else "other"


def timing_curves(rows):
    groups = {}
    for r in rows:
        groups.setdefault(group_of(r["x"]), []).append(r["days"])
        groups.setdefault("all", []).append(r["days"])
    curves = {}
    for g, ds in groups.items():
        if len(ds) < 30 and g != "all":
            continue
        ds = np.sort(np.array(ds))
        curves[g] = [[d, round(float(np.searchsorted(ds, d, side="right") / len(ds)), 4)] for d in GRID_DAYS]
    return curves


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--role", default="target", choices=["target", "all"], help="train on filings by the target company only (default) or everyone")
    ap.add_argument("--force", action="store_true", help="allow writing model.json from fewer than 300 labelled deals")
    a = ap.parse_args()

    rows = make_demo() if a.demo else load_real(a.role)
    if not rows:
        sys.exit("No labelled data found. Run collect.py (three stages) and label.py first.")
    if not a.demo and len(rows) < 300 and not a.force:
        sys.exit("Only %d labelled deals. That is too few to trust. Collect more or pass --force." % len(rows))
    rows.sort(key=lambda r: r["date"])
    X = np.array([[r["x"][f] for f in F.FEATURES] for r in rows])
    y = np.array([r["y"] for r in rows])
    n = len(rows)
    i1, i2 = int(n * 0.70), int(n * 0.85)
    tr, va, te = slice(0, i1), slice(i1, i2), slice(i2, n)
    print("%d deals, %.1f%% closed. Train %s to %s | validate to %s | test to %s" % (
        n, 100 * y.mean(), rows[0]["date"], rows[i1 - 1]["date"], rows[i2 - 1]["date"], rows[-1]["date"]))

    sc = StandardScaler().fit(X[tr])
    best = None
    for C in C_GRID:
        m = LogisticRegression(C=C, max_iter=2000).fit(sc.transform(X[tr]), y[tr])
        ll = log_loss(y[va], m.predict_proba(sc.transform(X[va]))[:, 1], labels=[0, 1])
        if best is None or ll < best[0]:
            best = (ll, C)
    C = best[1]
    lr = LogisticRegression(C=C, max_iter=2000).fit(sc.transform(X[tr]), y[tr])
    gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=0).fit(X[tr], y[tr])

    p_lr = lr.predict_proba(sc.transform(X[te]))[:, 1]
    results = {
        "base rate": metrics(y[te], np.full(len(y[te]), y[tr].mean())),
        "hand-written rules": metrics(y[te], [rules_prob(r["x"]) for r in rows[i2:]]),
        "logistic regression": metrics(y[te], p_lr),
        "gradient boosting": metrics(y[te], gb.predict_proba(X[te])[:, 1]),
    }
    print("\nTEST SET (newest %d deals, never used for fitting or tuning)" % len(y[te]))
    print("%-22s %8s %9s %6s" % ("model", "Brier", "log loss", "AUC"))
    for k, v in results.items():
        print("%-22s %8.4f %9.4f %6s" % (k, v["brier"], v["log_loss"], "n/a" if v["auc"] is None else "%.3f" % v["auc"]))
    print("(lower Brier and log loss are better; the model has to beat 'base rate' to be worth using)")
    print("\nCalibration of the logistic model on the test set:")
    for c in results["logistic regression"]["calibration"]:
        print("  predicted %s  n=%4d  mean predicted %.3f  actually closed %.3f" % (c["range"], c["n"], c["mean_pred"], c["actual"]))

    # Final model on all the data, same settings
    sc_all = StandardScaler().fit(X)
    final = LogisticRegression(C=C, max_iter=2000).fit(sc_all.transform(X), y)
    export = {
        "version": 1, "demo": bool(a.demo), "trained_at": datetime.utcnow().isoformat() + "Z", "role": a.role,
        "n_deals": n, "date_range": [rows[0]["date"], rows[-1]["date"]], "close_rate": float(y.mean()), "C": C,
        "features": F.FEATURES, "mean": sc_all.mean_.tolist(), "scale": sc_all.scale_.tolist(),
        "coef": final.coef_[0].tolist(), "intercept": float(final.intercept_[0]),
        "test": results, "timing": timing_curves(rows),
    }
    path = os.path.join(data_dir(), "model.demo.json" if a.demo else "model.json")
    with open(path, "w") as f:
        json.dump(export, f, indent=1)
    print("\nwrote", path)
    order = np.argsort(-np.abs(final.coef_[0]))[:8]
    print("Strongest features:", ", ".join("%s (%+.2f)" % (F.FEATURES[i], final.coef_[0][i]) for i in order))
    if a.demo:
        print("\nDEMO ONLY: this used synthetic data. server.py will not load model.demo.json.")


if __name__ == "__main__":
    main()
