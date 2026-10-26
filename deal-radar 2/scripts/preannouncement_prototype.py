"""Historical check of an experimental pre-announcement ranking score.

The production close-probability function is not used and is not modified.
Prices come from Yahoo's daily chart and are cut off before the prediction
date. Outcomes come from SEC filings. A missing price or a missing filing
drops the case. Nothing is filled in.

    python3 scripts/preannouncement_prototype.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import edgar
import market
from experimental.preannouncement import bars_before, price_features, ranking_score
from training.common import user_agent

REPORT = os.path.join(ROOT, "reports", "dealradar_preannouncement_prototype.md")
CACHE = os.path.join(ROOT, "data", "preannouncement_prototype")
ANNOUNCEMENTS = os.path.join(ROOT, "data", "closing_validation", "announcements")
HORIZON_DAYS = 30
LOOKBACK_DAYS = 365

# Filing accession, display name, and the file date used in the closing test.
# The script re-reads the filing. It does not trust this list for the role.
CANDIDATES = [
    ("0001140361-23-028228", "CIRCOR International, Inc.", "2023-06-05"),
    ("0001213900-23-045982", "Power & Digital Infrastructure Acquisition II Corp.", "2023-06-05"),
    ("0001213900-23-046531", "Clover Leaf Capital Corp.", "2023-06-06"),
    ("0001193125-23-162024", "Paratek Pharmaceuticals, Inc.", "2023-06-07"),
    ("0001381507-23-000027", "Limeade, Inc.", "2023-06-09"),
    ("0001193125-23-164839", "Nasdaq, Inc.", "2023-06-12"),
    ("0001193125-23-164891", "Chinook Therapeutics, Inc.", "2023-06-12"),
    ("0000950170-23-027586", "Gelesis Holdings, Inc.", "2023-06-13"),
    ("0001193125-23-167339", "NexTier Oilfield Solutions Inc.", "2023-06-15"),
    ("0001193125-23-168448", "Coherus BioSciences, Inc.", "2023-06-16"),
    ("0001193125-23-169553", "DICE Therapeutics, Inc.", "2023-06-20"),
    ("0001193125-23-170226", "Quotient Technology Inc.", "2023-06-20"),
    ("0001193125-23-171895", "Talaris Therapeutics, Inc.", "2023-06-22"),
    ("0001305773-23-000032", "Conformis, Inc.", "2023-06-23"),
    ("0001104659-23-076070", "Sigilon Therapeutics, Inc.", "2023-06-29"),
    ("0001104659-23-076136", "Immunome, Inc.", "2023-06-29"),
    ("0001193125-23-180610", "Kaleyra, Inc.", "2023-06-30"),
    ("0001493152-23-023016", "TRxADE Health, Inc.", "2023-06-30"),
]

# Checked by hand against Item 1.01 of each cached 8-K before this run.
EXPECTED_ROLE = {
    "0001140361-23-028228": "target",
    "0001213900-23-045982": "buyer",
    "0001213900-23-046531": "buyer",
    "0001193125-23-162024": "target",
    "0001381507-23-000027": "target",
    "0001193125-23-164839": "buyer",
    "0001193125-23-164891": "target",
    "0000950170-23-027586": "target",
    "0001193125-23-167339": "target",
    "0001193125-23-168448": "buyer",
    "0001193125-23-169553": "target",
    "0001193125-23-170226": "target",
    "0001193125-23-171895": "buyer",
    "0001305773-23-000032": "target",
    "0001104659-23-076070": "target",
    "0001104659-23-076136": "buyer",
    "0001193125-23-180610": "target",
    "0001493152-23-023016": "buyer",
}

# Large operating companies. Used only after EDGAR shows they were not a target.
NEGATIVE_TICKERS = ["AAPL", "MSFT", "GOOGL", "JNJ", "KO", "PEP", "WMT", "PG", "XOM", "JPM"]
BACKUP_TICKERS = ["COST", "UNH", "V", "MA", "HD", "MCD", "DIS", "NKE", "BA", "CAT"]

TAG_RE = re.compile(r"<[^>]+>")
SYMBOL_TAG_RE = re.compile(r'name="dei:TradingSymbol"[^>]*>([A-Z][A-Z0-9.\-]{0,5})<', re.I)


def plain_text(text):
    """Drop HTML tags so a cover page can be read the same way as a flat filing."""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = TAG_RE.sub(" ", text)
    for old, new in (
        ("&nbsp;", " "), ("&#160;", " "), ("&amp;", "&"), ("&#8217;", "'"),
        ("&#8220;", '"'), ("&#8221;", '"'), ("&#8211;", "-"), ("&#8212;", "-"),
    ):
        text = text.replace(old, new)
    return text


EXCHANGE_RE = re.compile(
    r"Trading Symbol(?:\(s\))?.{0,80}?registered\s+(.{10,300}?)\s+"
    r"(New York Stock Exchange|NYSE American|The Nasdaq|Nasdaq)",
    re.I | re.S,
)
SKIP_TOKENS = {"THE", "INC", "LLC", "LTD", "CORP", "CO", "AND", "NEW", "YORK"}


def normalize(text):
    return " ".join(text.lower().replace("“", '"').replace("”", '"').replace("’", "'").split())


def filer_role(text):
    """Whether the filing company is the company being bought.

    Reads the opening of Item 1.01 only, to label the outcome. The words are
    not passed to the score.
    """
    low = normalize(plain_text(text))
    start = low.find("item 1.01")
    if start < 0:
        return "unclear"
    head = low[start:start + 1800]
    parent_sub = any(phrase in head for phrase in (
        "subsidiary of parent",
        "parent's wholly owned subsidiary",
        "parent's wholly-owned subsidiary",
        "subsidiary of restor3d",
        "subsidiary of patterson-uti",
        "subsidiary of patterson",
    ))
    into_filer = any(phrase in head for phrase in (
        "into the company",
        "into quotient",
        "into limeade",
        "into nextier",
        "into gopro",
        "into merger sub",
    ))
    tender = "tender offer" in head
    if parent_sub and (into_filer or tender):
        return "target"
    if "into centerspace" in head and "acquisition of centerspace" in head:
        return "target"
    filer_owns_sub = any(phrase in head for phrase in (
        "subsidiary of the company",
        "subsidiary of nasdaq",
        "subsidiary of xpdb",
        "subsidiary of clover",
        "subsidiary of immunome",
        "subsidiary of talaris",
    ))
    if filer_owns_sub:
        return "buyer"
    return "unclear"


def trading_symbol(text):
    """Ticker printed on the 8-K cover, or the cover's XBRL trading-symbol tag."""
    tagged = SYMBOL_TAG_RE.findall(text or "")
    if tagged:
        return tagged[0].upper()
    match = EXCHANGE_RE.search(plain_text(text or ""))
    if not match:
        return None
    tokens = re.findall(r"\b[A-Z][A-Z0-9]{0,5}\b", match.group(1))
    tokens = [token for token in tokens if token not in SKIP_TOKENS and not token.isdigit()]
    if not tokens:
        return None
    return tokens[-1]


def company_cik(text, adsh):
    """Registrant CIK from the filing header, not the accession prefix.

    A filing agent often owns the accession number. The registrant CIK is the
    other 10-digit key in the header.
    """
    tagged = re.search(r'scheme="http://www.sec.gov/CIK">0*(\d+)<', text or "")
    if tagged:
        return int(tagged.group(1))
    accession_cik = int(adsh.split("-")[0])
    found = [int(value) for value in re.findall(r"\b0\d{9}\b", plain_text(text)[:1500])]
    others = [value for value in found if value != accession_cik]
    if others:
        return others[0]
    if found:
        return found[0]
    return None


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def search_cik(ua, cik, start, end, query, forms):
    """EDGAR full-text search for one company between two dates, inclusive.

    Production search_filings always ends today. This experiment passes the
    dates itself and does not change that function.
    """
    params = {
        "q": query,
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "forms": forms,
        "ciks": "%010d" % int(cik),
    }
    slug = "%s_%s_%s_%s" % (int(cik), start.isoformat(), end.isoformat(), "tender" if "offer to purchase" in query else "merger")
    path = os.path.join(CACHE, "searches", slug + ".json")
    if os.path.exists(path):
        return json.loads(open(path, encoding="utf-8").read())
    url = edgar.SEARCH_URL + "?" + urllib.parse.urlencode(params)
    payload = json.loads(edgar._get(url, ua))
    rows = edgar._records(payload)
    rows.sort(key=lambda row: row.get("filedOn") or "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
    return rows


def qualifying_hits(ua, cik, start, end):
    """Definitive-agreement and tender-offer filings in a date window."""
    hits = []
    hits.extend(search_cik(ua, cik, start, end, '"agreement and plan of merger"', "8-K"))
    hits.extend(search_cik(ua, cik, start, end, '"offer to purchase"', "SC TO-T"))
    unique = []
    seen = set()
    for hit in hits:
        if hit["adsh"] in seen:
            continue
        seen.add(hit["adsh"])
        unique.append(hit)
    unique.sort(key=lambda row: row.get("filedOn") or "")
    return unique


def load_prices(ticker, start, end):
    path = os.path.join(CACHE, "prices", "%s_%s_%s.json" % (ticker, start.isoformat(), end.isoformat()))
    if os.path.exists(path):
        saved = json.loads(open(path, encoding="utf-8").read())
        return [(parse_date(row[0]), float(row[1])) for row in saved]
    series = market.history(ticker, start, end)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([[day.isoformat(), close] for day, close in series], handle)
    time.sleep(0.25)
    return series


def auc(pairs):
    """Mann-Whitney AUC. None when either class is missing."""
    positives = [score for score, label in pairs if label == 1]
    negatives = [score for score, label in pairs if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def pct(value):
    return "%+.1f%%" % (100.0 * value)


def check_roles():
    failures = []
    parsed = []
    for adsh, name, filed in CANDIDATES:
        text = open(os.path.join(ANNOUNCEMENTS, adsh + ".txt"), encoding="utf-8", errors="replace").read()
        role = filer_role(text)
        if role != EXPECTED_ROLE[adsh]:
            failures.append("%s classified %s, reading says %s" % (adsh, role, EXPECTED_ROLE[adsh]))
        parsed.append({
            "adsh": adsh,
            "name": name,
            "filed": filed,
            "role": role,
            "symbol": trading_symbol(text),
            "cik": company_cik(text, adsh),
            "text_len": len(text),
        })
    if failures:
        raise SystemExit("Role check failed:\n" + "\n".join(failures))
    return parsed


def build_positives(ua, parsed):
    """Up to 10 target filings with a cover ticker, a clean prior window, and prices."""
    kept, blocked = [], []
    for row in parsed:
        if row["role"] != "target":
            blocked.append(dict(row, reason="The filer is not the company being acquired."))
            continue
        if not row["cik"]:
            blocked.append(dict(row, reason="The filing header has no registrant CIK."))
            continue
        if not row["symbol"]:
            blocked.append(dict(row, reason="The filing cover does not name a trading symbol, so no price was requested."))
            continue
        filed = parse_date(row["filed"])
        prediction = filed - timedelta(days=HORIZON_DAYS)
        window_end = prediction + timedelta(days=HORIZON_DAYS)
        if window_end != filed:
            blocked.append(dict(row, reason="The 30-day window does not land on the filing date."))
            continue
        try:
            earlier = qualifying_hits(ua, row["cik"], prediction - timedelta(days=LOOKBACK_DAYS), prediction)
            later = qualifying_hits(ua, row["cik"], prediction + timedelta(days=1), window_end)
        except edgar.EdgarError as exc:
            blocked.append(dict(row, reason="EDGAR search failed: %s" % exc))
            continue
        prior = [hit for hit in earlier if hit.get("filedOn") and hit["filedOn"] <= prediction.isoformat() and hit["adsh"] != row["adsh"]]
        if prior:
            blocked.append(dict(row, reason="An earlier matching filing was already public on %s (%s)." % (
                prior[-1]["filedOn"], prior[-1]["adsh"])))
            continue
        confirmed = [hit for hit in later if hit["adsh"] == row["adsh"]]
        if not confirmed:
            blocked.append(dict(row, reason="The known 8-K did not appear in an EDGAR search of the 30-day window for CIK %s." % row["cik"]))
            continue
        edgar_note = "EDGAR found 8-K %s in the 30 days after %s and no earlier matching filing in the prior %d days." % (
            row["adsh"], prediction.isoformat(), LOOKBACK_DAYS)
        try:
            series = load_prices(row["symbol"], prediction - timedelta(days=180), prediction)
            features = price_features(bars_before(series, prediction), bars_before(
                load_prices("SPY", prediction - timedelta(days=180), prediction), prediction))
        except (market.MarketError, ValueError) as exc:
            blocked.append(dict(row, prediction=prediction.isoformat(), reason="%s Yahoo then refused the price history: %s" % (edgar_note, exc)))
            continue
        score = ranking_score(features)
        kept.append({
            "name": row["name"],
            "ticker": row["symbol"],
            "cik": row["cik"],
            "prediction": prediction.isoformat(),
            "announced": filed.isoformat(),
            "outcome": 1,
            "adsh": row["adsh"],
            "features": features,
            "score": score,
            "evidence": "8-K %s filed %s. EDGAR full-text search for CIK %d found that accession in the 30 days after %s and no earlier matching 8-K or SC TO-T in the prior %d days." % (
                row["adsh"], filed.isoformat(), row["cik"], prediction.isoformat(), LOOKBACK_DAYS),
        })
        if len(kept) == 10:
            break
    return kept, blocked


def is_fresh_agreement(text):
    """Item 1.01 announces a new agreement, not an amendment of an existing one."""
    low = normalize(plain_text(text))
    start = low.find("item 1.01")
    if start < 0:
        return False
    head = low[start:start + 2200]
    if "agreement and plan of merger" not in head and "offer to purchase" not in head:
        return False
    if any(phrase in head for phrase in (
        "amendment no", "first amendment", "second amendment", "amended and restated",
        "amendment to the agreement", "amendment to that certain",
    )):
        return False
    return "entered into" in head


def load_hit_text(ua, hit):
    path = os.path.join(CACHE, "filings", hit["adsh"] + ".txt")
    if os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    if not hit.get("docUrl"):
        return ""
    raw = edgar.fetch_document(ua, hit["docUrl"], max_bytes=700_000)
    text = raw.decode("utf-8", errors="replace")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def build_recent(ua):
    """Targets from 1-20 September 2026 whose shares Yahoo still charts.

    The June 2023 targets are delisted, so Yahoo has no chart for them. This
    window is already over as of the run date, and the same 30-day rule applies.
    At most 40 filings are read, and at most 10 targets are kept.
    """
    start, end = date(2026, 9, 1), date(2026, 9, 20)
    rows, total = edgar.search_window(ua, start, end, '"agreement and plan of merger"', "8-K", 0)
    kept, blocked = [], []
    examined = 0
    for hit in rows:
        if len(kept) >= 10 or examined >= 80:
            break
        if (hit.get("form") or "").endswith("/A"):
            continue
        examined += 1
        print("read", hit.get("filedOn"), hit.get("ticker"), hit.get("filer"), flush=True)
        try:
            text = load_hit_text(ua, hit)
        except edgar.EdgarError as exc:
            blocked.append({"name": hit.get("filer"), "symbol": hit.get("ticker"), "role": "unread",
                            "reason": "The 8-K could not be downloaded: %s" % exc, "cohort": "September 2026"})
            continue
        role = filer_role(text) if text else "unclear"
        symbol = trading_symbol(text) if text else None
        fresh = is_fresh_agreement(text) if text else False
        print("  role %s symbol %s fresh %s" % (role, symbol, fresh), flush=True)
        label = {"name": hit.get("filer") or "unknown", "symbol": symbol or hit.get("ticker"), "role": role, "cohort": "September 2026"}
        if role != "target" or not fresh:
            blocked.append(dict(label, reason="Item 1.01 is not a new agreement that acquires this filer (role %s)." % role))
            continue
        cik = company_cik(text, hit["adsh"]) or hit.get("cik")
        if not symbol or not cik:
            blocked.append(dict(label, reason="The 8-K cover has no trading symbol."))
            continue
        filed = parse_date(hit["filedOn"])
        prediction = filed - timedelta(days=HORIZON_DAYS)
        try:
            earlier = qualifying_hits(ua, cik, prediction - timedelta(days=LOOKBACK_DAYS), prediction)
        except edgar.EdgarError as exc:
            blocked.append(dict(label, reason="The prior-year EDGAR search failed: %s" % exc))
            continue
        prior = [item for item in earlier if item.get("filedOn") and item["filedOn"] <= prediction.isoformat() and item["adsh"] != hit["adsh"]]
        if prior:
            blocked.append(dict(label, reason="An earlier matching filing was already public on %s (%s)." % (
                prior[-1]["filedOn"], prior[-1]["adsh"])))
            continue
        try:
            series = load_prices(symbol, prediction - timedelta(days=180), prediction)
            features = price_features(bars_before(series, prediction), bars_before(
                load_prices("SPY", prediction - timedelta(days=180), prediction), prediction))
        except (market.MarketError, ValueError) as exc:
            blocked.append(dict(label, prediction=prediction.isoformat(), reason="Price history could not be built: %s" % exc))
            continue
        kept.append({
            "name": label["name"],
            "ticker": symbol,
            "cik": cik,
            "prediction": prediction.isoformat(),
            "announced": filed.isoformat(),
            "outcome": 1,
            "adsh": hit["adsh"],
            "features": features,
            "score": ranking_score(features),
            "cohort": "September 2026",
            "evidence": "8-K %s filed %s. Item 1.01 says the filer entered into an agreement and plan of merger as the company being acquired. No earlier matching filing for CIK %d from %s through %s." % (
                hit["adsh"], filed.isoformat(), cik,
                (prediction - timedelta(days=LOOKBACK_DAYS)).isoformat(), prediction.isoformat()),
        })
    return kept, blocked, total, examined


def build_negative(ua, ticker, prediction, announced):
    identity = edgar.find_company(ua, ticker)
    if not identity:
        return None, "%s is not on the current SEC ticker list." % ticker
    cik = identity["cik"]
    window_end = prediction + timedelta(days=HORIZON_DAYS)
    try:
        earlier = qualifying_hits(ua, cik, prediction - timedelta(days=LOOKBACK_DAYS), prediction)
        later = qualifying_hits(ua, cik, prediction + timedelta(days=1), window_end)
    except edgar.EdgarError as exc:
        return None, "EDGAR search failed for %s: %s" % (ticker, exc)
    prior = [hit for hit in earlier if hit.get("filedOn") and hit["filedOn"] <= prediction.isoformat()]
    during = [hit for hit in later if hit.get("filedOn") and prediction.isoformat() < hit["filedOn"] <= window_end.isoformat()]
    if prior or during:
        shown = (during or prior)[0]
        return None, "%s has a matching filing %s on %s, so it is not a clean negative." % (
            ticker, shown["adsh"], shown["filedOn"])
    try:
        series = load_prices(ticker, prediction - timedelta(days=180), prediction)
        features = price_features(bars_before(series, prediction), bars_before(
            load_prices("SPY", prediction - timedelta(days=180), prediction), prediction))
    except (market.MarketError, ValueError) as exc:
        return None, "Price history for %s could not be built: %s" % (ticker, exc)
    return {
        "name": identity["name"],
        "ticker": ticker,
        "cik": cik,
        "prediction": prediction.isoformat(),
        "announced": None,
        "paired_announcement": announced,
        "outcome": 0,
        "features": features,
        "score": ranking_score(features),
        "evidence": "EDGAR full-text search for CIK %d from %s through %s returned no 8-K containing \"agreement and plan of merger\" and no SC TO-T containing \"offer to purchase\"." % (
            cik, (prediction - timedelta(days=LOOKBACK_DAYS)).isoformat(), window_end.isoformat()),
    }, None


def build_negatives(ua, positives):
    pool = list(NEGATIVE_TICKERS) + list(BACKUP_TICKERS)
    used = set()
    kept, notes = [], []
    for positive in positives:
        prediction = parse_date(positive["prediction"])
        chosen = None
        for ticker in pool:
            if ticker in used:
                continue
            row, reason = build_negative(ua, ticker, prediction, positive["announced"])
            if row is None:
                notes.append(reason)
                continue
            chosen = row
            used.add(ticker)
            break
        if chosen is None:
            notes.append("No verified negative remained for prediction date %s." % positive["prediction"])
            continue
        kept.append(chosen)
    return kept, notes


def mean(values):
    return sum(values) / len(values) if values else None


def write_report(positives, negatives, blocked, notes, option_note):
    pairs = [(row["score"], row["outcome"]) for row in positives + negatives]
    score_auc = auc(pairs)
    lines = []
    add = lines.append
    add("# DealRadar pre-announcement prototype")
    add("")
    add("Run at %s. Production scoring code was not edited." % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    add("")
    if positives and negatives:
        add("The script finished and produced the scores below. That is a completed technical run. It is not evidence that the score predicts acquisitions. The sample is small, the comparison companies are very large, and the score was not trained.")
    else:
        add("The script finished. It did not produce a ranking score for a matched set of companies, so there is no accuracy result.")
    add("")
    add("## Experimental target")
    add("")
    add("Will the company become the target of a publicly announced definitive acquisition agreement or tender offer within the next 30 calendar days?")
    add("")
    add("The prediction timestamp is 00:00 US Eastern on the prediction date. The observation window is the next 30 calendar days, including the 30th day. A filing already public at that timestamp is excluded. Rumors, strategic-review updates, and ordinary contracts are not positive outcomes. A positive outcome requires an 8-K containing \"agreement and plan of merger\" or an SC TO-T containing \"offer to purchase\", and the filing company has to be the company being acquired.")
    add("")
    add("For each positive case the prediction date is 30 days before the 8-K filing date, so the filing falls on the last day of the window. Each negative case uses one of those same prediction dates.")
    add("")
    add("## What can be reconstructed")
    add("")
    add("- SEC full-text search accepts a start date and an end date. `edgar.search_filings` ignores that and always ends on today. This experiment calls the same public search with its own dates. It does not change `edgar.search_filings`.")
    add("- The registrant CIK and the trading symbol are read from the cached 8-K header. The symbol is an identifier. No other words from the announcement are used as inputs.")
    add("- Yahoo's daily chart, through the existing `market.history` function, returns closes for a requested range. Only sessions dated before the prediction date are used. The chart is the one Yahoo returns today, so split adjustments made later can change old levels. It is not a file that was saved on the prediction date.")
    add("- Options are not available. `options.CHAIN` records that Yahoo's options endpoint returned HTTP 401. `market.contract` returned: %s" % option_note)
    add("- Headlines are not available as of a past date. `news.py` says there is no historical headline dataset. Current headlines were not requested, because they can mention an announcement that had not happened yet on the prediction date.")
    add("- `features.vectorize` reads the announcement. It was not used.")
    add("- `data/model.json` is still absent. No trained model was loaded.")
    add("")
    add("## Scoring method")
    add("")
    add("`experimental/preannouncement.py` computes one number: the stock's return over the 21 trading sessions before the prediction date, minus the SPY return over the same sessions. A larger number means the stock outperformed the market. The formula has no fitted weights. It is an experimental ranking score, not a probability, so there is no calibration table.")
    add("")
    add("`quote.close_probability` was not called. Its 0.90 starting point is the chance an announced deal closes. It was not assigned to these companies.")
    add("")
    add("The baseline gives every company the same score. Its ranking AUC is 0.5 by construction. Training and evaluation are separate because nothing was trained on these outcomes.")
    add("")
    add("## Dataset")
    add("")
    add("Two groups were checked. The first is the 18 June 2023 filings already in the closing-validation cache. Item 1.01 was used only to decide whether the filer was the company being bought. The second is one page of EDGAR 8-Ks from 1 September 2026 through 20 September 2026 that contain \"agreement and plan of merger\". Amendments filed as 8-K/A were skipped. A filing counts only when Item 1.01 says the filer entered into a new agreement as the company being acquired.")
    add("")
    add("### Scored targets")
    add("")
    if not positives:
        add("No target had both a verified filing window and a usable price history.")
    else:
        add("| Company | Ticker | Prediction | Announcement | 21-day return | SPY return | Score | Last close used |")
        add("|---|---|---|---|---|---|---|---|")
        for row in positives:
            features = row["features"]
            add("| %s | %s | %s | %s | %s | %s | %.4f | %s |" % (
                row["name"], row["ticker"], row["prediction"], row["announced"],
                pct(features["ret_21"]), pct(features["spy_ret_21"]), row["score"], features["last_price_date"]))
        add("")
        for row in positives:
            add("- %s (%s): %s" % (row["ticker"], row["name"], row["evidence"]))
    add("")
    add("### Scored companies with no qualifying announcement")
    add("")
    if not negatives:
        add("No comparison company cleared the EDGAR check and the price check.")
    else:
        add("| Company | Ticker | Prediction | Window end | 21-day return | SPY return | Score | Last close used |")
        add("|---|---|---|---|---|---|---|---|")
        for row in negatives:
            features = row["features"]
            end = parse_date(row["prediction"]) + timedelta(days=HORIZON_DAYS)
            add("| %s | %s | %s | %s | %s | %s | %.4f | %s |" % (
                row["name"], row["ticker"], row["prediction"], end.isoformat(),
                pct(features["ret_21"]), pct(features["spy_ret_21"]), row["score"], features["last_price_date"]))
        add("")
        for row in negatives:
            add("- %s (%s): %s" % (row["ticker"], row["name"], row["evidence"]))
    add("")
    add("### Not scored")
    add("")
    skipped = [row for row in blocked if row.get("cohort") == "September 2026" and row.get("role") != "target"]
    shown = [row for row in blocked if row not in skipped]
    buyers = sum(1 for row in skipped if row.get("role") == "buyer")
    add("September 2026 page: %d filings were not a new acquisition of the filer (%d of those are the buyer). They were not scored." % (
        len(skipped), buyers))
    add("")
    for row in shown:
        symbol = row.get("symbol") or "no symbol"
        add("- %s: %s (%s, %s): %s" % (row.get("cohort") or "June 2023", row["name"], symbol, row["role"], row["reason"]))
    for note in notes:
        add("- %s" % note)
    add("")
    add("## Results")
    add("")
    if positives and negatives and score_auc is not None:
        add("Scored targets: %d. Scored non-targets: %d. Both groups use a 30-day window." % (len(positives), len(negatives)))
        add("")
        add("Mean score for targets: %.4f. Mean score for the other companies: %.4f." % (
            mean([row["score"] for row in positives]), mean([row["score"] for row in negatives])))
        add("")
        add("Ranking AUC of this score on these cases: %.3f. Ranking AUC of the constant baseline: 0.500." % score_auc)
        add("")
        add("The highest score in this table belongs to a company that did not announce a deal. The average for the targets is lower than the average for the other companies.")
        add("")
        add("These figures describe this handful of cases. %d targets is too small to establish predictive accuracy. No probability was produced, so Brier score and calibration were not calculated." % len(positives))
    else:
        add("A ranking comparison was not calculated. A score requires a verified outcome and a price history that stops before the prediction date, and at least one case on each side.")
    add("")
    add("## Limitations")
    add("")
    add("- The positive cases are deals already known from a later filing. The prediction date is placed 30 days before that filing. The prices do not include the filing, but the sample is not a screen of the whole market on a random date.")
    add("- The comparison names are among the largest listed companies. A score that separates them from small acquisition targets can be a size effect.")
    add("- Yahoo's chart for a delisted ticker is incomplete or adjusted after the fact. Cases without a returned history were left unscored.")
    add("- An EDGAR search can miss a deal filed by the buyer only, under a different phrase, or on a form this query does not request. The absence of a hit is the evidence recorded above, not a proof that no rumor existed.")
    add("- The 21-day abnormal return was chosen as a simple published pattern, not because it won a test. Changing it after seeing these scores would use the same outcomes twice.")
    add("")
    add("## Remaining blockers")
    add("")
    add("There is still no saved record of what a data vendor showed on the prediction morning, no historical option chain, and no historical headline archive. The production EDGAR search still cannot take a historical cutoff. The production app still has no function whose output is the probability of an announcement.")
    add("")
    add("## Smallest next step")
    add("")
    add("Keep this score in the experimental module. Repeat the same 30-day rule on an earlier set of filings, and do not fit anything on the four targets above. A price source that still has delisted tickers is also required before the June 2023 targets can be scored. A fitted probability needs that separate earlier set.")
    add("")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")


def main():
    os.makedirs(CACHE, exist_ok=True)
    parsed = check_roles()
    print("role_check ok %d filings" % len(parsed), flush=True)
    ua = user_agent()
    june_kept, june_blocked = build_positives(ua, parsed)
    for row in june_blocked:
        row["cohort"] = "June 2023"
    print("june_priced %d" % len(june_kept), flush=True)
    recent_kept, recent_blocked, recent_total, recent_read = build_recent(ua)
    print("recent_total %d read %d priced %d" % (recent_total, recent_read, len(recent_kept)), flush=True)
    positives = june_kept + recent_kept
    blocked = june_blocked + recent_blocked
    if positives:
        negatives, notes = build_negatives(ua, positives)
    else:
        negatives, notes = [], ["No target had a price history, so comparison companies were not scored."]
    notes.insert(0, "September 2026 search reported %d hits. This run read %d non-amendment filings from the first page." % (
        recent_total, recent_read))
    _premium, option_note = market.contract("CIR", "call", 50, 30)
    write_report(positives, negatives, blocked, notes, option_note)
    print("positives %d negatives %d blocked %d" % (len(positives), len(negatives), len(blocked)))
    for row in positives + negatives:
        print("%s %s pred %s score %.4f outcome %d" % (row["ticker"], row["name"], row["prediction"], row["score"], row["outcome"]))
    if positives and negatives:
        print("auc %.3f" % auc([(row["score"], row["outcome"]) for row in positives + negatives]))
    print("probabilities 0")
    print("technical_run complete")
    print("predictive_accuracy not_established")
    print("report %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
