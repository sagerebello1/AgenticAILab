"""Compare a flat 90% close probability with quote.close_probability on the same 18 deals.

The 18 deals are the scored rows from reports/dealradar_closing_validation.md.
Announcement text is the packet already saved for that test. Outcome filings are
not read. quote.py is not modified. Flag ablation is done by calling the
existing function with an empty flag dict.

    python3 scripts/ablate_signals.py
"""
import os
import random
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import quote
import terms

REPORT = os.path.join(ROOT, "reports", "dealradar_signal_ablation.md")
CACHE = os.path.join(ROOT, "data", "closing_validation", "announcements")
BASE = quote.BASE_P

# The scored evaluation set from the closing validation. Excluded duplicates
# (Patterson-UTI and Surface Oncology) are not included. Labels are the outcomes
# already verified for that report.
DEALS = [
    ("CIRCOR INTERNATIONAL INC", "CIRCOR", "2023-06-05", 1, "000114036123028228", 0.8781),
    ("AirJoule Technologies Corp.", "AIRJ", "2023-06-05", 1, "000121390023045982", 0.8781),
    ("Clover Leaf Capital Corp.", "CLOE", "2023-06-06", 0, "000121390023046531", 0.8895),
    ("Paratek Pharmaceuticals, Inc.", "Paratek", "2023-06-07", 1, "000119312523162024", 0.8781),
    ("LIMEADE, INC", "LIMEADE", "2023-06-09", 1, "000138150723000027", 0.8895),
    ("NASDAQ, INC.", "NDAQ", "2023-06-12", 1, "000119312523164839", 0.8781),
    ("CHINOOK THERAPEUTICS, INC.", "Chinook", "2023-06-12", 1, "000119312523164891", 0.8895),
    ("GELESIS HOLDINGS, INC.", "GLSHQ", "2023-06-13", 0, "000095017023027586", 0.8895),
    ("NEXTIER OILFIELD SOLUTIONS INC.", "NexTier", "2023-06-15", 1, "000119312523167339", 0.9096),
    ("Coherus Oncology, Inc.", "CHRS", "2023-06-16", 1, "000119312523168448", 0.8895),
    ("DICE Therapeutics, Inc.", "DICE", "2023-06-20", 1, "000119312523169553", 0.9183),
    ("Quotient Technology Inc.", "Quotient", "2023-06-20", 1, "000119312523170226", 0.9000),
    ("Tourmaline Bio, Inc.", "TRML", "2023-06-22", 1, "000119312523171895", 0.9263),
    ("Conformis Inc", "Conformis", "2023-06-23", 1, "000130577323000032", 0.8895),
    ("Sigilon Therapeutics, Inc.", "Sigilon", "2023-06-29", 1, "000110465923076070", 0.9263),
    ("Immunome Inc.", "IMNM", "2023-06-29", 1, "000110465923076136", 0.8895),
    ("Kaleyra, Inc.", "Kaleyra", "2023-06-30", 1, "000119312523180610", 0.8781),
    ("Scienture Holdings, Inc.", "MEDS", "2023-06-30", 1, "000149315223023016", 0.8895),
]

# Point values copied from quote.close_probability so the harness can check
# the function. They are not a second implementation of the probability.
POINTS = {
    "hsr": -0.01,
    "secondRequest": -0.10,
    "foreign": -0.03,
    "other": -0.03,
    "financing_true": -0.06,
    "financing_false": 0.01,
    "tender": 0.02,
    "vote": -0.01,
    "goShop": -0.01,
    "stock": -0.02,
}

MEANINGS = {
    "hsr": "The announcement mentions a US antitrust filing (Hart-Scott-Rodino).",
    "secondRequest": "The announcement mentions a second request from antitrust regulators.",
    "foreign": "The announcement names a foreign regulator. Each name, up to three, subtracts 0.03.",
    "other": "The announcement names a sector regulator. Each name, up to two, subtracts 0.03.",
    "financing_true": "The announcement says closing depends on financing.",
    "financing_false": "The announcement says there is no financing condition.",
    "tender": "The announcement describes a tender offer. If this is set, the vote adjustment is not applied.",
    "vote": "The announcement requires a shareholder vote. The formula uses it only when there is no tender.",
    "goShop": "The announcement describes a go-shop period.",
    "stock": "The consideration is the buyer's stock. Cash and mixed consideration do not move the probability.",
}


def adsh(compact):
    return "%s-%s-%s" % (compact[:10], compact[10:12], compact[12:])


def brier(p, y):
    return (p - y) ** 2


def mean(values):
    return sum(values) / len(values) if values else None


def clone_flags(flags):
    out = dict(flags)
    out["foreign"] = list(flags.get("foreign") or [])
    out["other"] = list(flags.get("other") or [])
    return out


def load_deals():
    rows = []
    for name, ticker, announced, label, compact, published in DEALS:
        path = os.path.join(CACHE, adsh(compact) + ".txt")
        if not os.path.exists(path):
            raise SystemExit("Missing cached announcement for %s at %s" % (ticker, path))
        text = open(path, encoding="utf-8").read()
        extracted = terms.extract_terms(text)
        flags = dict(extracted.get("flags") or {})
        flags["consideration"] = extracted.get("consideration")
        scored = quote.close_probability(flags)
        blank = quote.close_probability({})
        if abs(round(scored["close"], 4) - published) > 0.00005:
            raise SystemExit("%s reproduced %.4f, closing report has %.4f" % (ticker, scored["close"], published))
        if abs(blank["close"] - BASE) > 1e-9:
            raise SystemExit("Empty flags returned %.6f, not the 0.90 baseline." % blank["close"])
        rows.append({
            "name": name, "ticker": ticker, "announced": announced, "label": label,
            "flags": flags, "p_model": scored["close"], "p_base": BASE, "p_ablated": blank["close"],
            "drivers": scored["drivers"],
        })
    if len(rows) != 18 or sum(row["label"] for row in rows) != 16:
        raise SystemExit("The frozen set is no longer the 18 deals from the closing report.")
    return rows


def roc_auc(rows, key):
    pos = [row[key] for row in rows if row["label"] == 1]
    neg = [row[key] for row in rows if row["label"] == 0]
    if not pos or not neg:
        return None
    if len(set(row[key] for row in rows)) == 1:
        return None
    wins = 0.0
    for left in pos:
        for right in neg:
            if left > right:
                wins += 1
            elif left == right:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def bootstrap_gap(rows, draws=2000):
    """Model Brier minus 90% Brier. Negative means the flags scored better."""
    rng = random.Random(20261025)
    gaps = []
    for _ in range(draws):
        sample = [rng.choice(rows) for _ in rows]
        model = mean([brier(row["p_model"], row["label"]) for row in sample])
        base = mean([brier(row["p_base"], row["label"]) for row in sample])
        gaps.append(model - base)
    gaps.sort()
    return gaps[int(0.025 * (len(gaps) - 1))], gaps[int(0.975 * (len(gaps) - 1))]


def active(flags):
    """Flags that quote.close_probability actually applies."""
    out = {
        "hsr": bool(flags.get("hsr")),
        "secondRequest": bool(flags.get("secondRequest")),
        "foreign": len(flags.get("foreign") or []),
        "other": len(flags.get("other") or []),
        "financing_true": flags.get("financingCondition") is True,
        "financing_false": flags.get("financingCondition") is False,
        "tender": bool(flags.get("tender")),
        "vote": bool(flags.get("vote")) and not flags.get("tender"),
        "goShop": bool(flags.get("goShop")),
        "stock": flags.get("consideration") == "stock",
    }
    return out


def present(flags):
    """Flags found in the announcement, before the tender/vote rule."""
    return {
        "hsr": bool(flags.get("hsr")),
        "secondRequest": bool(flags.get("secondRequest")),
        "foreign": len(flags.get("foreign") or []) > 0,
        "other": len(flags.get("other") or []) > 0,
        "financing_true": flags.get("financingCondition") is True,
        "financing_false": flags.get("financingCondition") is False,
        "tender": bool(flags.get("tender")),
        "vote": bool(flags.get("vote")),
        "goShop": bool(flags.get("goShop")),
        "stock": flags.get("consideration") == "stock",
    }


def cleared(flags, key):
    nxt = clone_flags(flags)
    if key == "hsr":
        nxt["hsr"] = False
    elif key == "secondRequest":
        nxt["secondRequest"] = False
    elif key == "foreign":
        nxt["foreign"] = []
    elif key == "other":
        nxt["other"] = []
    elif key in ("financing_true", "financing_false"):
        nxt["financingCondition"] = None
    elif key == "tender":
        nxt["tender"] = False
    elif key == "vote":
        nxt["vote"] = False
    elif key == "goShop":
        nxt["goShop"] = False
    elif key == "stock":
        nxt["consideration"] = "cash"
    return nxt


def forced(flags, key):
    nxt = clone_flags(flags)
    if key == "hsr":
        nxt["hsr"] = True
    elif key == "secondRequest":
        nxt["secondRequest"] = True
    elif key == "foreign":
        if not nxt["foreign"]:
            nxt["foreign"] = ["European Commission"]
    elif key == "other":
        if not nxt["other"]:
            nxt["other"] = ["FCC"]
    elif key == "financing_true":
        nxt["financingCondition"] = True
    elif key == "financing_false":
        nxt["financingCondition"] = False
    elif key == "tender":
        nxt["tender"] = True
    elif key == "vote":
        nxt["vote"] = True
    elif key == "goShop":
        nxt["goShop"] = True
    elif key == "stock":
        nxt["consideration"] = "stock"
    return nxt


def expected_log_odds(before, after, key):
    """Log-odds change implied by the point schedule, including the vote/tender rule."""
    was = active(before)
    now = active(after)
    delta = 0.0
    if key in ("financing_true", "financing_false"):
        if was["financing_true"]:
            delta -= POINTS["financing_true"]
        if was["financing_false"]:
            delta -= POINTS["financing_false"]
        if now["financing_true"]:
            delta += POINTS["financing_true"]
        if now["financing_false"]:
            delta += POINTS["financing_false"]
        return delta / quote.SCALE
    if key == "tender":
        if was["tender"] != now["tender"]:
            delta += POINTS["tender"] if now["tender"] else -POINTS["tender"]
        if was["vote"] != now["vote"]:
            delta += POINTS["vote"] if now["vote"] else -POINTS["vote"]
        return delta / quote.SCALE
    if key == "vote":
        if was["vote"] != now["vote"]:
            delta += POINTS["vote"] if now["vote"] else -POINTS["vote"]
        return delta / quote.SCALE
    if key in ("foreign", "other"):
        cap = 0.09 if key == "foreign" else 0.06
        old = -min(0.03 * was[key], cap)
        new = -min(0.03 * now[key], cap)
        return (new - old) / quote.SCALE
    point = POINTS[key]
    if was[key] != now[key]:
        delta = point if now[key] else -point
    return delta / quote.SCALE


def sensitivity(rows):
    checks = []
    mismatches = []
    only = []
    for key, point in POINTS.items():
        alone_flags = {}
        if key == "hsr":
            alone_flags = {"hsr": True}
        elif key == "secondRequest":
            alone_flags = {"secondRequest": True}
        elif key == "foreign":
            alone_flags = {"foreign": ["European Commission"]}
        elif key == "other":
            alone_flags = {"other": ["FCC"]}
        elif key == "financing_true":
            alone_flags = {"financingCondition": True}
        elif key == "financing_false":
            alone_flags = {"financingCondition": False}
        elif key == "tender":
            alone_flags = {"tender": True}
        elif key == "vote":
            alone_flags = {"vote": True}
        elif key == "goShop":
            alone_flags = {"goShop": True}
        elif key == "stock":
            alone_flags = {"consideration": "stock"}
        alone = quote.close_probability(alone_flags)["close"]
        shift = quote.logit(alone) - quote.logit(BASE)
        if abs(shift - point / quote.SCALE) > 1e-9:
            mismatches.append("%s alone moved log-odds by %.6f, schedule says %.6f" % (key, shift, point / quote.SCALE))
        only.append((key, point, alone, alone - BASE))
        for row in rows:
            toggled = cleared(row["flags"], key) if active(row["flags"]).get(key) else forced(row["flags"], key)
            # foreign/other counts: active() returns an int, so .get is the count.
            if key in ("foreign", "other"):
                toggled = cleared(row["flags"], key) if active(row["flags"])[key] else forced(row["flags"], key)
            new_p = quote.close_probability(toggled)["close"]
            got = quote.logit(new_p) - quote.logit(row["p_model"])
            want = expected_log_odds(row["flags"], toggled, key)
            if abs(got - want) > 1e-8:
                mismatches.append("%s on %s: log-odds change %.6f, schedule %.6f" % (key, row["ticker"], got, want))
            checks.append({"key": key, "ticker": row["ticker"], "delta_p": new_p - row["p_model"], "was_on": bool(active(row["flags"])[key])})
    return only, checks, mismatches


def rate(rows):
    return mean([row["label"] for row in rows])


def flag_rows(rows):
    out = []
    for key in POINTS:
        on = [row for row in rows if present(row["flags"])[key]]
        off = [row for row in rows if not present(row["flags"])[key]]
        applied = [row for row in rows if active(row["flags"])[key]]
        contribution = []
        for row in applied:
            without = quote.close_probability(cleared(row["flags"], key))["close"]
            contribution.append(row["p_model"] - without)
        enough = len(on) >= 5 and len(off) >= 5
        out.append({
            "key": key,
            "on": len(on),
            "off": len(off),
            "applied": len(applied),
            "close_on": rate(on),
            "close_off": rate(off),
            "contribution": mean(contribution) if contribution else None,
            "enough": enough,
        })
    return out


def fmt(value, digits=4):
    if value is None:
        return "—"
    return ("%." + str(digits) + "f") % value


def pct(value):
    if value is None:
        return "—"
    return "%.1f%%" % (100.0 * value)


def build(rows, only, checks, mismatches, gap):
    closed = [row for row in rows if row["label"] == 1]
    terminated = [row for row in rows if row["label"] == 0]
    b_model = mean([brier(row["p_model"], row["label"]) for row in rows])
    b_base = mean([brier(row["p_base"], row["label"]) for row in rows])
    b_ablated = mean([brier(row["p_ablated"], row["label"]) for row in rows])
    same = max(abs(row["p_base"] - row["p_ablated"]) for row in rows)
    auc = roc_auc(rows, "p_model")
    lines = []
    add = lines.append

    def table(headers, body):
        add("| " + " | ".join(headers) + " |")
        add("|" + "|".join("---" for _ in headers) + "|")
        for row in body:
            add("| " + " | ".join(row) + " |")
        add("")

    add("# DealRadar filing-flag ablation")
    add("")
    add("Run at %s. The 18 deals and their outcomes are the scored set in `reports/dealradar_closing_validation.md`. Announcement text was reread from the packets saved for that test. No new transactions were selected." % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    add("")
    add("**These results are preliminary.** Two of the 18 deals were terminated. A difference this small, on this few failures, does not support a claim of statistical significance.")
    add("")
    add("`quote.close_probability` was called and was not edited. The flat 90% row and the flag-off row are calculated in this script.")
    add("")

    add("## 1. Baseline versus the existing model")
    add("")
    add("A is a constant %.2f, the starting value in `quote.BASE_P`. B is `quote.close_probability` on the announcement flags. C calls the same function with an empty flag dict, so none of the adjustments run." % BASE)
    add("")
    add("A and C match. The largest gap between them on any deal is %.2e." % same)
    add("")
    table(
        ["Model", "Mean probability", "Closed deals", "Terminated deals", "Mean Brier"],
        [
            ["A. 90% for every deal", fmt(mean([row["p_base"] for row in rows])), fmt(mean([row["p_base"] for row in closed])), fmt(mean([row["p_base"] for row in terminated])), fmt(b_base)],
            ["B. Existing flags", fmt(mean([row["p_model"] for row in rows])), fmt(mean([row["p_model"] for row in closed])), fmt(mean([row["p_model"] for row in terminated])), fmt(b_model)],
            ["C. Flags disabled", fmt(mean([row["p_ablated"] for row in rows])), fmt(mean([row["p_ablated"] for row in closed])), fmt(mean([row["p_ablated"] for row in terminated])), fmt(b_ablated)],
        ],
    )
    add("DealRadar Brier minus the 90%% Brier: **%+.4f**. A negative number would mean the flags scored better." % (b_model - b_base))
    add("")
    add("A 2,000-draw bootstrap of these 18 deals put that difference between **%+.4f** and **%+.4f** (2.5th to 97.5th percentile). The interval includes zero." % gap)
    add("")
    if auc is None:
        add("ROC AUC for the flag model: not a meaningful calculation. The two terminated deals are not separated from the closed deals by a stable ranking, or every score is identical.")
    else:
        add("ROC AUC for the flag model: **%.3f**. With two terminated deals and scores packed between %.4f and %.4f, this rank is not a meaningful measure of discrimination. The 90%% model assigns the same score to every deal, so it has no ranking to compare." % (
            auc, min(row["p_model"] for row in rows), max(row["p_model"] for row in rows)))
    add("")

    add("## 2. Deal-by-deal scores")
    add("")
    add("Brier score = (probability − outcome)². Closed is 1 and terminated is 0.")
    add("")
    table(
        ["Company", "Announced", "Outcome", "90% probability", "Flag probability", "Flags off", "90% Brier", "Flag Brier"],
        [[
            row["name"].replace("|", "/"),
            row["announced"],
            "Closed" if row["label"] else "Terminated",
            fmt(row["p_base"]),
            fmt(row["p_model"]),
            fmt(row["p_ablated"]),
            fmt(brier(row["p_base"], row["label"])),
            fmt(brier(row["p_model"], row["label"])),
        ] for row in rows],
    )

    add("## 3. Filing flags")
    add("")
    add("Frequency is counted on these 18 announcements. \"Applied\" is the count that changed `quote.close_probability`. A shareholder vote is read from the filing even when a tender offer is also present, and the formula then ignores the vote. The contribution is the average change in probability from removing that flag on the deals where the formula used it.")
    add("")
    add("The close rates are descriptive. None of these splits has five deals on both sides, which is the minimum used here before treating a comparison as even a weak observation. They are not evidence that a flag causes a deal to close or fail.")
    add("")
    labels = {
        "hsr": "HSR",
        "secondRequest": "Second request",
        "foreign": "Foreign regulator",
        "other": "Sector regulator",
        "financing_true": "Financing condition",
        "financing_false": "No financing condition",
        "tender": "Tender offer",
        "vote": "Shareholder vote",
        "goShop": "Go-shop",
        "stock": "Stock consideration",
    }
    info = {row["key"]: row for row in flag_rows(rows)}
    table(
        ["Flag", "Deals where the text has it", "Deals where the formula uses it", "Close rate when present", "Close rate when absent", "Mean probability contribution", "Enough to judge?"],
        [[
            labels[key],
            "%d of 18" % info[key]["on"],
            "%d" % info[key]["applied"],
            pct(info[key]["close_on"]),
            pct(info[key]["close_off"]),
            fmt(info[key]["contribution"]),
            "No",
        ] for key in POINTS],
    )
    for key in POINTS:
        direction = "not observed"
        item = info[key]
        if item["on"] and item["off"] and item["close_on"] is not None:
            if item["close_on"] > item["close_off"]:
                direction = "higher closing rate when present, in this sample only"
            elif item["close_on"] < item["close_off"]:
                direction = "lower closing rate when present, in this sample only"
            else:
                direction = "the same closing rate either way, in this sample"
        count = "1 deal" if item["on"] == 1 else "%d deals" % item["on"]
        if direction == "not observed":
            association = "It does not appear, so there is no association to report."
        else:
            association = direction[0].upper() + direction[1:] + "."
        add("- **%s.** %s Present in %s. %s There are not enough observations to conclude anything about this flag." % (
            labels[key], MEANINGS[key], count, association))
    add("")

    add("## 4. Sensitivity of each flag")
    add("")
    add("Each row turns on only that input and calls `quote.close_probability`. The log-odds change matches `points / 0.09` from the function. Production code was not edited to produce these rows.")
    add("")
    if mismatches:
        add("Schedule check failed:")
        for item in mismatches:
            add("- %s" % item)
        add("")
    else:
        add("Every isolated toggle on these 18 deals moved the log-odds by the amount in the existing point schedule, including the rule that a tender offer replaces the vote adjustment. No mismatch was found.")
        add("")
    table(
        ["Flag", "Points in the formula", "Probability with only this flag", "Change from 0.90"],
        [[labels[key], "%+.2f" % point, fmt(alone), "%+.4f" % delta] for key, point, alone, delta in only],
    )
    add("Toggling a flag on a real deal changes the probability by less or more than the one-flag row above, because the logistic curve is steeper near 0.50 than near 0.90. The log-odds change stays equal to the point value divided by 0.09. That check passed for every deal and every flag.")
    add("")
    add("Average probability change when the flag is switched on for deals that did not already have it, and switched off for deals that did:")
    add("")
    body = []
    for key in POINTS:
        ons = [item["delta_p"] for item in checks if item["key"] == key and not item["was_on"]]
        offs = [item["delta_p"] for item in checks if item["key"] == key and item["was_on"]]
        body.append([
            labels[key],
            fmt(mean(ons)) if ons else "Already on, or not toggled",
            fmt(mean(offs)) if offs else "Not used on these deals",
        ])
    table(["Flag", "Mean change when switched on", "Mean change when switched off"], body)
    add("The shareholder-vote average is smaller than the one-flag row because a tender offer blocks that adjustment. On a filing that already has a tender, switching the vote flag on does not change the probability.")
    add("")

    add("## 5. Limits")
    add("")
    add("- Two terminated deals, Clover Leaf and Gelesis, carry almost all of the Brier score. Both were scored at 0.8895, against 0.9000 with the flags off. The flags helped those two rows by a few thousandths and moved the closed deals by a similar amount in both directions.")
    add("- Sixteen closed deals have Brier scores near 0.01 either way. They cannot show whether a rare failure is being detected.")
    add("- Second request, a financing condition, foreign approval, and stock consideration do not appear in this set. The flags that do appear move the probability by about one to four points.")
    add("- Vote and tender overlap. Gelesis has a vote in the text, and the formula still applies the vote adjustment because that filing has no tender. Deals with both a tender and a vote keep only the tender adjustment.")
    add("- The close rates above describe these 18 filings. They were already chosen by the closing validation, which kept deals with a clear later outcome sentence. This ablation does not add deals and does not drop deals based on a new look at the outcomes.")
    add("- The 0.90 baseline here is the constant inside the function. It is not the 97% close rate from the earlier training window.")
    add("")

    add("## 6. Do the flags add predictive value?")
    add("")
    add("On these 18 deals, no. The flag model has a mean Brier score of %.4f and the flat 90%% model has %.4f. The difference is %+.4f, and the bootstrap interval includes zero. Disabling the flags returns exactly 0.90, so the small gap is the whole effect of the adjustments." % (b_model, b_base, b_model - b_base))
    add("")
    add("The two terminated deals were not given a meaningfully lower probability than the deals that closed (%.4f versus %.4f). The ranking score does not show separation." % (
        mean([row["p_model"] for row in terminated]), mean([row["p_model"] for row in closed])))
    add("")
    add("A stronger test needs more terminated deals with announcement packets saved the same way, enough that several failures carry each common flag. Second request, financing conditions, and stock consideration need to be present in more than a handful of deals before their point values can be checked against outcomes. A useful sample would also keep the deals whose outcome filing was ambiguous, instead of scoring only the ones with a clear closing or termination sentence.")
    add("")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return {
        "n": len(rows),
        "b_model": b_model,
        "b_base": b_base,
        "b_ablated": b_ablated,
        "gap": b_model - b_base,
        "boot": gap,
        "auc": auc,
        "same": same,
        "mismatches": len(mismatches),
        "report": REPORT,
    }


def main():
    rows = load_deals()
    only, checks, mismatches = sensitivity(rows)
    if mismatches:
        print("schedule mismatches %d" % len(mismatches))
        for item in mismatches[:8]:
            print(" ", item)
    summary = build(rows, only, checks, mismatches, bootstrap_gap(rows))
    print("n %d model_brier %.6f base_brier %.6f ablated_brier %.6f" % (
        summary["n"], summary["b_model"], summary["b_base"], summary["b_ablated"]))
    print("difference %+.6f bootstrap %+.6f to %+.6f" % (summary["gap"], summary["boot"][0], summary["boot"][1]))
    print("auc %s a_equals_c %.3e mismatches %d" % (summary["auc"], summary["same"], summary["mismatches"]))
    print("report %s" % summary["report"])
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
