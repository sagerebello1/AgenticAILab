"""Check whether DealRadar can score a company before an M&A announcement.

The production functions are called and not modified. A company with no announcement
filing is not given a made-up acquisition probability.

    python3 scripts/preannouncement_feasibility.py
"""
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import features
import model as model_mod
import news
import quote
import terms
import workflow

REPORT = os.path.join(ROOT, "reports", "dealradar_preannouncement_feasibility.md")


def probe():
    loaded = model_mod.load()
    blank_quote = quote.close_probability({})
    blank_terms = terms.estimate_probabilities(None, {})
    empty_features, empty_terms = features.vectorize("")
    headline = news.score([])
    shell = {
        "filingStatus": "no_relevant_filing", "offer": None, "market": {},
        "catalyst": {"kind": "unverified"},
    }
    try:
        quote.respond({})
        quote_error = None
    except quote.InputError as exc:
        quote_error = str(exc)
    nonzero = sorted(name for name, value in empty_features.items() if value)
    return {
        "model_loaded": loaded is not None,
        "model_path_exists": os.path.exists(model_mod.PATH),
        "quote_blank": blank_quote["close"],
        "terms_blank": blank_terms[0],
        "quote_error": quote_error,
        "listed": workflow.listed_company(shell),
        "active": workflow.active_quoted(shell),
        "feature_count": len(empty_features),
        "nonzero_features": nonzero,
        "empty_offer": empty_terms.get("offer"),
        "news_adjustment": headline["adjustment"],
        "news_headlines": len(headline["headlines"]),
    }


def build(result):
    lines = []
    add = lines.append
    add("# DealRadar pre-announcement feasibility")
    add("")
    add("Run at %s. Production scoring code was called and was not edited." % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    add("")
    add("**A historical test of pre-announcement ranking was not run.** No existing function emits the probability that a company will announce a deal. There are no valid pre-announcement probabilities to score, so no Brier score and no ROC AUC are reported.")
    add("")
    add("## 1. What the pipeline scores")
    add("")
    add("The live book is built by `server.scan`. It searches SEC EDGAR for an 8-K containing \"agreement and plan of merger\" or an SC TO-T containing \"offer to purchase\". `server.lookup_symbol` uses those same two searches for one company. A row is kept only when `workflow.listed_company` is true: the filing quotes a per-share cash price, and a stock price and a break price are both present.")
    add("")
    add("`edgar.search_filings` always ends the search window on today's date. It has no argument for a historical prediction date.")
    add("")
    add("Once a filing is in hand, two functions estimate the chance that the announced deal eventually closes:")
    add("")
    add("- `quote.close_probability` starts at 0.90 and adjusts filing flags in log-odds. With no flags, this run returned **%.4f**." % result["quote_blank"])
    add("- `terms.estimate_probabilities` starts at 0.93 and adds the same flags. With no flags, this run returned **%.3f**." % result["terms_blank"])
    add("")
    add("Those two numbers are the starting points for an announced deal. They are not the probability that a deal will be announced. `server._search_company_deals` says this in the message it returns when a company has no merger filing: the unchanged company list is not a close chance of zero.")
    add("")
    add("`data/model.json` exists: %s. `model.load()` returned a model: %s. The trained path in `server.build_deal` calls `features.vectorize` on the announcement text and then `model.predict`. With the file absent, that path does not run." % (
        "yes" if result["model_path_exists"] else "no", "yes" if result["model_loaded"] else "no"))
    add("")
    add("## 2. Which functions can run before an announcement")
    add("")
    add("| Function | What it returns before an announcement | Acquisition probability |")
    add("|---|---|---|")
    add("| `edgar.find_company` | Company name and CIK for a ticker | No |")
    add("| `market.history`, `market.identity`, `market.index_quote` | Delayed daily prices | No |")
    add("| `market.contract` | No options chain. The module records that Yahoo's options endpoint returned HTTP 401 | No |")
    add("| `news.score` | A headline adjustment. This run, with no headlines, returned **%.3f** and %d headlines | No. `news.apply` only shifts a probability it is given |" % (
        result["news_adjustment"], result["news_headlines"]))
    add("| `workflow.listed_company` | This run, on a company with no filing and no offer, returned **%s** | No |" % result["listed"])
    add("| `quote.respond` with no offer | This run raised: %s | No |" % result["quote_error"])
    add("")
    add("`features.vectorize` on empty text produced %d features. The only nonzero names were: %s. The extracted offer was %s. An all-zero filing vector is not a pre-announcement score, and nothing in the server turns it into one while `model.load()` is empty." % (
        result["feature_count"],
        ", ".join(result["nonzero_features"]) if result["nonzero_features"] else "none",
        result["empty_offer"]))
    add("")
    add("## 3. Which functions need the announcement")
    add("")
    add("- `terms.extract_terms` and both close-probability functions read flags from the merger or tender filing. Those flags are the offer form, antitrust language, financing, a vote, a tender, and a go-shop. They are not knowable from the company alone.")
    add("- `quote.respond` and `workflow.recalculate` also need the cash offer, the stock price, and the break price. The offer comes from the filing. The probability itself does not use the stock price.")
    add("- `pricing.scenario_value` and `options.analyze` value an option on an announced cash deal. They take `p_close` as an input.")
    add("- `training/collect.py` gathers historical 8-Ks that already contain a merger agreement. `training/label.py` then labels whether that announced deal closed. The training features in `features.py` are taken from the announcement text.")
    add("- `news.apply` moves an existing close probability. Its weights are hand-set, and the module says there is no historical headline dataset. A headline feed read today can mention an announcement that has already happened.")
    add("")
    add("## 4. Whether a pre-announcement probability exists")
    add("")
    add("No. The probe did not produce one.")
    add("")
    add("Calling the close-probability function with empty flags returns %.4f from `quote.close_probability` and %.3f from `terms.estimate_probabilities`. Using either number as the chance a company will be acquired would repeat the mistake rejected in the first validation: the app does not assign that number to a company with no filing." % (
        result["quote_blank"], result["terms_blank"]))
    add("")
    add("A worked example from the closing-validation set shows the gap. CIRCOR's merger agreement was filed on 2023-06-05, and that packet is what `quote.close_probability` scored. A prediction date of 2023-06-04 would need inputs that existed that day. The flags in the 2023-06-05 filing did not exist yet. The code has no other feature vector for CIRCOR on 2023-06-04, and `search_filings` cannot be asked for \"filings visible on 2023-06-04\" because the window always ends today.")
    add("")
    add("The same block applies to any of the other 17 scored deals, and to companies with no later announcement. Positive and negative cases would both be unscored. A Brier score or a ROC AUC on invented scores would not be an evaluation.")
    add("")
    add("## 5. What is missing")
    add("")
    add("- A function whose output is the probability of an announcement inside a stated horizon, such as 90 days.")
    add("- Inputs that exist before the filing. Prices can be read from `market.history` for a past date, but no probability function accepts them. Options premiums are unavailable. There is no saved history of headlines, fundamentals, or ownership.")
    add("- An as-of date on the EDGAR search, so a test can see only filings that were public on the prediction date.")
    add("- A labeled set of companies that were not announced, built without using the later outcome to choose the score.")
    add("")
    add("## 6. Smallest change that would make a test possible")
    add("")
    add("Add one new scoring function that takes only pre-announcement inputs and returns a probability of an announcement within a fixed horizon. Point the EDGAR search at a historical as-of date, and save the inputs as of that date. Then score companies that later announced and companies that did not, over the same horizon.")
    add("")
    add("Saving the current filing flags earlier cannot do this. Those flags are parsed from the announcement. The 0.90 and 0.93 constants should not be reused as the pre-announcement score. This experiment does not add that function and does not change `quote.close_probability`.")
    add("")
    path = REPORT
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return path


def main():
    result = probe()
    path = build(result)
    print("model_loaded %s" % result["model_loaded"])
    print("quote_blank %.4f terms_blank %.3f" % (result["quote_blank"], result["terms_blank"]))
    print("listed %s quote_error %s" % (result["listed"], result["quote_error"]))
    print("nonzero_features %s" % (result["nonzero_features"] or "none"))
    print("preannouncement_probabilities 0")
    print("report %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
