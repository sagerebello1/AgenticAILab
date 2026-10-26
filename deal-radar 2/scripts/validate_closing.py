"""Test whether quote.close_probability estimates the chance an announced deal closes.

The production functions are not modified. Announcement-time flags come from the
announcement filing only. Outcomes come from a later filing whose text states that
the merger closed or that the merger agreement was terminated.

The comparison baseline is the close rate in an earlier window. It is not the
close rate of the deals being scored.

    python3 scripts/validate_closing.py
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "training"))

import edgar
import quote
import server
import terms
from common import user_agent

REPORT = os.path.join(ROOT, "reports", "dealradar_closing_validation.md")
CACHE = os.path.join(ROOT, "data", "closing_validation")
WINDOW_DAYS = 540
TRAIN_START, TRAIN_END = date(2022, 1, 3), date(2022, 6, 30)
EVAL_START, EVAL_END = date(2023, 6, 1), date(2024, 3, 31)
TRAIN_VERIFIED_CAP = 40
EVAL_VERIFIED_CAP = 20
TRAIN_EXAMINED_CAP = 120
EVAL_EXAMINED_CAP = 140
MIN_OUTCOME_DAYS = 7
CLOSE_FORMS = {"25", "25-NSE", "15-12B", "15-12G"}
CLOSE_EVENT = re.compile(
    r"(?:merger|business combination).{0,80}(?:was |has been |been )?(?:consummated|completed|closed)|"
    r"(?:consummat(?:ed|ion)|completion|closing) of (?:the |its |their )?(?:merger|business combination)|"
    r"certificate of merger|(?:merger|business combination) became effective|effective time of the merger|"
    r"completed (?:its |the |their )?previously announced (?:merger|business combination)",
    re.I,
)
TERM_EVENT = re.compile(
    r"(?:merger agreement|agreement and plan of (?:merger|reorganization)|business combination agreement)"
    r".{0,220}?(?:was terminated|has been terminated|have terminated|agreed to terminate)|"
    r"(?:was terminated|has been terminated|have terminated|agreed to terminate).{0,220}?"
    r"(?:merger agreement|agreement and plan of (?:merger|reorganization)|business combination agreement)",
    re.I | re.S,
)


def ensure_dirs():
    for sub in ("", "submissions", "docs", "announcements"):
        os.makedirs(os.path.join(CACHE, sub) if sub else CACHE, exist_ok=True)


def git_info():
    def run(args):
        try:
            return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (subprocess.CalledProcessError, OSError):
            return ""
    short = run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    subject = run(["git", "log", "-1", "--format=%s"]) or "unknown"
    dirty = run(["git", "diff", "--name-only", "HEAD", "--", "quote.py", "terms.py", "options.py", "workflow.py"])
    names = [os.path.basename(line.strip()) for line in dirty.splitlines() if line.strip()]
    return {"short": short, "subject": subject.rstrip("."), "dirty": names}


def snippet(text, match):
    a = max(0, match.start() - 90)
    b = min(len(text), match.end() + 90)
    raw = re.sub(r"\s+", " ", text[a:b]).strip()
    raw = raw.replace("|", "/")
    return raw[:280]


def close_match_rejected(body, match):
    """Drop a close phrase that is a negation, a condition, or a description of a later step."""
    pre = body[max(0, match.start() - 50):match.start()]
    post = body[match.end():match.end() + 70]
    if re.search(r"\b(not|no|never|without|failed|failure|unable)\b", pre, re.I):
        if not re.search(r"\buntil\b", post, re.I):
            return True
    if re.search(r"in order to\s+$", pre, re.I):
        return True
    window = pre + match.group(0)
    if re.search(r"effective time of the merger", match.group(0), re.I):
        if re.search(r"following the|prior to the|before the|after the", window, re.I):
            return True
    return False


def classify(text, kind):
    body = (text or "")[:30000]
    closed = CLOSE_EVENT.search(body)
    terminated = TERM_EVENT.search(body)
    if kind == "close" and closed and not terminated and not close_match_rejected(body, closed):
        return 1, snippet(body, closed)
    if kind == "term" and terminated and not closed:
        return 0, snippet(body, terminated)
    return None, None


def is_original_announcement(text):
    """True when this filing is the signing 8-K, not a later amendment."""
    if not text:
        return False
    marker = re.search(r"item\s+1\.01", text, re.I)
    body = text[marker.start():marker.start() + 5000] if marker else text[:5000]
    flat = re.sub(r"\s+", " ", body)
    if re.search(
            r"\b(?:first|second|third|fourth|fifth|sixth)\s+amendment\b|"
            r"amendment no\.?\s*\d+\s+to|amended and restated (?:agreement and plan|sponsor agreement)",
            flat, re.I):
        return False
    return bool(re.search(
        r"entered into (?:an |the )?(?:agreement and plan of merger|merger agreement|business combination agreement)",
        flat, re.I))


def cached_fetch(url):
    key = re.sub(r"[^A-Za-z0-9._-]", "_", url)[-180:]
    path = os.path.join(CACHE, "docs", key + ".txt")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    last = None
    for _ in range(3):
        try:
            text = terms.to_text(edgar.fetch_document(user_agent(), url, max_bytes=2_000_000))[:200000]
            if text:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            return text
        except edgar.EdgarError as exc:
            last = str(exc)
            if "HTTP 429" in last or "HTTP 503" in last:
                time.sleep(3)
                continue
            print("  fetch failed: %s" % last)
            return ""
    print("  fetch failed: %s" % last)
    return ""


def load_submissions(cik):
    path = os.path.join(CACHE, "submissions", "%d.json" % cik)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    try:
        sub = edgar.submissions(user_agent(), cik)
    except edgar.EdgarError as exc:
        print("  submissions failed for %s: %s" % (cik, exc))
        return None
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(sub, handle)
    return sub


def filing_url(cik, adsh, doc):
    return "%s/%d/%s/%s" % (edgar.ARCHIVES, int(cik), adsh.replace("-", ""), doc)


def index_url(cik, adsh):
    return "%s/%d/%s/%s-index.htm" % (edgar.ARCHIVES, int(cik), adsh.replace("-", ""), adsh)


def outcome_packet(cik, filing):
    """8-K body plus press releases. The merger-agreement exhibit is not read."""
    parts, urls = [], []
    doc = filing.get("doc") or ""
    if doc:
        url = filing_url(cik, filing["adsh"], doc)
        urls.append(url)
        parts.append(cached_fetch(url))
    text = "\n".join(part for part in parts if part)
    if classify(text, "close")[0] is not None or classify(text, "term")[0] is not None:
        return text, urls
    try:
        listed = edgar.list_documents(user_agent(), index_url(cik, filing["adsh"]))
    except edgar.EdgarError as exc:
        print("  index failed %s: %s" % (filing["adsh"], exc))
        return text, urls
    extras = 0
    for doc_row in listed:
        kind = (doc_row.get("type") or "").upper()
        if not kind.startswith("EX-99") or extras >= 2:
            continue
        extras += 1
        urls.append(doc_row["url"])
        parts.append(cached_fetch(doc_row["url"]))
    return "\n".join(part for part in parts if part), urls


def item_set(filing):
    items = filing.get("items") or []
    if isinstance(items, str):
        items = [part.strip() for part in items.split(",") if part.strip()]
    return {str(item).lower().replace("item", "").strip() for item in items}


def is_announcement(rec):
    form = (rec.get("form") or "").upper()
    if form != "8-K":
        return False
    return "1.01" in item_set(rec) and rec.get("filedOn") and rec.get("cik") and rec.get("adsh")


def decisive_kind(filing):
    form = filing.get("form") or ""
    items = item_set(filing)
    if form in CLOSE_FORMS or (form in ("8-K", "8-K/A") and items & {"2.01", "5.01"}):
        return "close"
    if form in ("8-K", "8-K/A") and "1.02" in items:
        return "term"
    return None


def resolve_outcome(cik, filings, announced):
    start = date.fromisoformat(announced)
    deadline = start + timedelta(days=WINDOW_DAYS)
    looked = 0
    for filing in filings:
        try:
            filed = date.fromisoformat(filing["date"])
        except (TypeError, ValueError):
            continue
        if filed <= start or filed > deadline:
            continue
        kind = decisive_kind(filing)
        if not kind:
            continue
        looked += 1
        if looked > 8:
            break
        text, urls = outcome_packet(cik, filing)
        label, evidence = classify(text, kind)
        if label is None:
            continue
        return {
            "label": label,
            "outcomeDate": filing["date"],
            "outcomeForm": filing.get("form"),
            "outcomeAdsh": filing.get("adsh"),
            "evidence": evidence,
            "outcomeUrls": urls,
        }
    return None


def search_range(start, end):
    rows, seen = [], set()
    offset, total = 0, 1
    while offset < min(total, 400):
        try:
            recs, total = edgar.search_window(
                user_agent(), start, end, '"agreement and plan of merger"', "8-K", offset)
        except edgar.EdgarError as exc:
            print("search failed %s to %s: %s" % (start, end, exc))
            break
        if not recs:
            break
        for rec in recs:
            if rec["adsh"] not in seen:
                seen.add(rec["adsh"])
                rows.append(rec)
        offset += len(recs)
        if len(recs) < 100:
            break
    return rows


def windows(start, end, step=14):
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=step - 1), end)
        yield cur, win_end
        cur = win_end + timedelta(days=1)


def collect(role, start, end, verified_cap, examined_cap, blocked_ciks):
    chosen, seen_ciks = [], set(blocked_ciks)
    examined = unresolved = errors = not_original = too_soon = 0
    for win_start, win_end in windows(start, end):
        if len(chosen) >= verified_cap or examined >= examined_cap:
            break
        print("%s search %s to %s" % (role, win_start, win_end))
        hits = [rec for rec in search_range(win_start, win_end) if is_announcement(rec)]
        hits.sort(key=lambda rec: (rec["filedOn"], rec["adsh"]))
        for rec in hits:
            if len(chosen) >= verified_cap or examined >= examined_cap:
                break
            cik = int(rec["cik"])
            if cik in seen_ciks:
                continue
            seen_ciks.add(cik)
            examined += 1
            sub = load_submissions(cik)
            if not sub:
                errors += 1
                continue
            outcome = resolve_outcome(cik, sub.get("filings") or [], rec["filedOn"])
            if not outcome:
                unresolved += 1
                print("  unresolved %s %s" % (rec["filedOn"], rec.get("filer")))
                continue
            gap_days = (date.fromisoformat(outcome["outcomeDate"]) - date.fromisoformat(rec["filedOn"])).days
            if gap_days < MIN_OUTCOME_DAYS:
                too_soon += 1
                print("  too soon %s %s outcome %s" % (rec["filedOn"], rec.get("filer"), outcome["outcomeDate"]))
                continue
            tickers = sub.get("tickers") or []
            row = {
                "role": role,
                "adsh": rec["adsh"],
                "cik": cik,
                "filer": sub.get("name") or rec.get("filer"),
                "ticker": rec.get("ticker") or (tickers[0] if tickers else None),
                "announced": rec["filedOn"],
                "announcementUrl": rec.get("docUrl"),
                "indexUrl": index_url(cik, rec["adsh"]),
                "sic": sub.get("sic"),
            }
            row.update(outcome)
            text, payload = announcement_text(row)
            row["announcementText"] = text
            row["announcementError"] = (payload or {}).get("error")
            if not is_original_announcement(text):
                not_original += 1
                print("  not an original announcement %s %s" % (row["announced"], row["ticker"] or row["filer"]))
                continue
            chosen.append(row)
            print("  %s %s %s %s -> %s %s" % (
                role, "CLOSED" if outcome["label"] else "TERMINATED",
                row["announced"], row["ticker"] or row["filer"], outcome["outcomeDate"], outcome["evidence"][:120]))
    return chosen, {
        "examined": examined, "unresolved": unresolved, "errors": errors,
        "not_original": not_original, "too_soon": too_soon, "verified": len(chosen),
    }


def announcement_text(row):
    path = os.path.join(CACHE, "announcements", row["adsh"] + ".txt")
    meta = path + ".json"
    if os.path.exists(path) and os.path.exists(meta):
        return open(path, encoding="utf-8").read(), json.load(open(meta, encoding="utf-8"))
    rec = {
        "adsh": row["adsh"], "cik": row["cik"], "docUrl": row.get("announcementUrl"),
        "indexUrl": row["indexUrl"], "form": "8-K", "filer": row["filer"],
    }
    text, sources, error = server.read_filing(rec)
    payload = {"sources": sources, "error": error}
    if text:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text[:250000])
        with open(meta, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    return text or "", payload


def score_flags(extracted):
    flags = dict(extracted.get("flags") or {})
    flags["consideration"] = extracted.get("consideration")
    scored = quote.close_probability(flags)
    return flags, scored


COMMON_WORDS = {
    "group", "holdings", "holding", "capital", "partners", "acquisition", "international",
    "enterprises", "company", "nasdaq", "better", "therapeutics", "sciences", "solutions",
    "technologies", "technology", "energy", "financial", "global", "medical", "health",
    "services", "properties", "resources", "systems", "software", "bancorp",
    "bancshares", "therapeutics", "pharmaceuticals", "communications",
}


def party_words(filer):
    words = []
    for part in re.split(r"[^A-Za-z0-9]+", filer or ""):
        word = part.lower()
        if len(word) >= 5 and word not in COMMON_WORDS:
            words.append(word)
    return words[:3]


def same_transaction(left, right):
    gap = abs((date.fromisoformat(left["announced"]) - date.fromisoformat(right["announced"])).days)
    if gap > 7:
        return False
    left_words, right_words = party_words(left.get("filer")), party_words(right.get("filer"))
    if not left_words or not right_words:
        return False
    left_text, right_text = left.get("announcementText") or "", right.get("announcementText") or ""
    left_hit = any(re.search(r"\b%s\b" % re.escape(word), right_text, re.I) for word in left_words)
    right_hit = any(re.search(r"\b%s\b" % re.escape(word), left_text, re.I) for word in right_words)
    return left_hit and right_hit


def drop_duplicate_transactions(rows):
    """Drop a later filing of the same signing by the other party."""
    kept = []
    for row in sorted(rows, key=lambda item: (item["announced"], item["adsh"])):
        prior = next((item for item in kept if same_transaction(item, row)), None)
        if prior:
            row["excluded"] = "Same transaction as %s, filed %s." % (prior.get("ticker") or prior.get("filer"), prior["announced"])
            continue
        kept.append(row)
    return kept


def brier(p, y):
    return (p - y) ** 2


def roc_auc(rows):
    pos = [row["probability"] for row in rows if row["label"] == 1]
    neg = [row["probability"] for row in rows if row["label"] == 0]
    if not pos or not neg:
        return None
    wins = 0.0
    for left in pos:
        for right in neg:
            if left > right:
                wins += 1
            elif left == right:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def bootstrap_gap(rows, rate, draws=2000):
    if not rows:
        return None
    rng = random.Random(20261025)
    gaps = []
    for _ in range(draws):
        sample = [rng.choice(rows) for _ in rows]
        model = sum(brier(row["probability"], row["label"]) for row in sample) / len(sample)
        base = sum(brier(rate, row["label"]) for row in sample) / len(sample)
        gaps.append(base - model)
    gaps.sort()
    return {"low": gaps[int(0.025 * (len(gaps) - 1))], "high": gaps[int(0.975 * (len(gaps) - 1))]}


def flag_summary(flags):
    parts = []
    if flags.get("hsr"):
        parts.append("HSR")
    if flags.get("secondRequest"):
        parts.append("second request")
    foreign = flags.get("foreign") or []
    if foreign:
        parts.append("foreign: " + ", ".join(foreign))
    other = flags.get("other") or []
    if other:
        parts.append("sector: " + ", ".join(other))
    fin = flags.get("financingCondition")
    if fin is True:
        parts.append("financing condition")
    elif fin is False:
        parts.append("no financing condition")
    if flags.get("tender"):
        parts.append("tender")
    elif flags.get("vote"):
        parts.append("vote")
    if flags.get("goShop"):
        parts.append("go-shop")
    cons = flags.get("consideration")
    if cons:
        parts.append(cons)
    return ", ".join(parts) if parts else "no flags"


def formula_checks():
    probes = [
        ("No filing flags", {}),
        ("HSR", {"hsr": True}),
        ("Second request", {"secondRequest": True}),
        ("One foreign approval", {"foreign": ["European Commission"]}),
        ("One sector approval", {"other": ["FCC"]}),
        ("Financing condition", {"financingCondition": True}),
        ("Financing explicitly not required", {"financingCondition": False}),
        ("Tender offer", {"tender": True}),
        ("Shareholder vote, no tender", {"vote": True}),
        ("Go-shop", {"goShop": True}),
        ("Stock consideration", {"consideration": "stock"}),
    ]
    rows = []
    for label, flags in probes:
        scored = quote.close_probability(flags)
        rows.append((label, scored["close"], scored["legacy"]))
    blank = rows[0][1]
    if abs(blank - quote.BASE_P) > 1e-9:
        raise RuntimeError("quote.close_probability no longer returns the 0.90 base rate.")
    return rows


def mean(values):
    return sum(values) / len(values) if values else None


def pct(part, whole):
    return 100.0 * part / whole if whole else None


def fmt(value, digits=4):
    if value is None:
        return "Not calculated"
    return ("%." + str(digits) + "f") % value


def link(url):
    if not url:
        return "Not retrieved"
    return url


def build_report(meta):
    train, eval_rows = meta["train"], meta["eval"]
    valid = [row for row in eval_rows if row.get("probability") is not None and not row.get("excluded")]
    excluded = [row for row in eval_rows if row.get("excluded") or row.get("probability") is None]
    closed = [row for row in valid if row["label"] == 1]
    terminated = [row for row in valid if row["label"] == 0]
    train_closed = sum(row["label"] for row in train)
    rate = mean([row["label"] for row in train])
    model_brier = mean([row["brier"] for row in valid])
    base_brier = mean([brier(rate, row["label"]) for row in valid]) if rate is not None and valid else None
    gap = bootstrap_gap(valid, rate) if rate is not None and valid else None
    probs = [row["probability"] for row in valid]
    preliminary = len(valid) < 20 or len(train) < 20 or len(terminated) < 5
    lines = []
    add = lines.append

    def table(headers, rows):
        add("| " + " | ".join(headers) + " |")
        add("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            add("| " + " | ".join(row) + " |")
        add("")

    add("# DealRadar closing-probability validation")
    add("")
    add("Run at %s. Git %s, %s." % (meta["run_at"], meta["git"]["short"], meta["git"]["subject"]))
    add("")
    if preliminary:
        add("**These results are preliminary.** The evaluation sample, the separate training sample, or the number of terminated deals is smaller than a stable test needs.")
        add("")
    add("Production files differing from git HEAD: %s." % (", ".join(meta["git"]["dirty"]) if meta["git"]["dirty"] else "none of quote.py, terms.py, options.py, or workflow.py"))
    add("")
    add("`quote.close_probability` was called unchanged. No probability rule was edited for this test.")
    add("")

    add("## 1. Formula and inputs")
    add("")
    add("`quote.close_probability` estimates the chance that an already announced deal eventually closes. The docstring in `quote.py` calls this the filing chance and sets the starting point at nine in ten announced deals. It does not estimate whether a deal will be announced, and it does not use the stock price.")
    add("")
    add("The executed formula is:")
    add("")
    add("```")
    add("points = sum of the filing adjustments below")
    add("close = sigmoid(logit(%.2f) + points / %.2f)" % (quote.BASE_P, quote.SCALE))
    add("```")
    add("")
    add("`BASE_P` is %.2f. `SCALE` is %.2f, which is 0.90 times 0.10. One adjustment point therefore moves the log-odds by 1/0.09. The logistic function turns that sum back into a probability. A call with no flags returns %.4f." % (quote.BASE_P, quote.SCALE, quote.close_probability({})["close"]))
    add("")
    add("The same call also returns a legacy additive score, starting at 0.93 and clamped to 0.35–0.98. The number used in this test is the logistic `close` value, which is the score `quote.respond` uses when the caller does not override it.")
    add("")
    add("Adjustments, confirmed by calling the function once per flag:")
    add("")
    table(["Input present in the announcement filing", "Probability"], [
        [label, "%.4f" % prob] for label, prob, _legacy in meta["formula"]
    ])
    add("The point schedule inside the function is HSR -0.01, second request -0.10, each foreign regulator -0.03 (capped at -0.09), each sector regulator -0.03 (capped at -0.06), financing condition -0.06, financing explicitly absent +0.01, tender +0.02, shareholder vote without a tender -0.01, go-shop -0.01, and stock consideration -0.02.")
    add("")
    add("Inputs available at announcement are the words in that announcement's 8-K packet. This test reads them the same way the server does: the primary document, then a press release or exhibit only until a per-share price is found. Later closing filings and termination filings are not included in that packet.")
    add("")
    add("A flag is true when `terms.extract_terms` finds its phrase. \"Second request\" matches the words anywhere in that packet, including a condition in the agreement that describes a second request which has not been issued. That is how the current function behaves. This test does not correct it.")
    add("")

    add("## 2. Transactions and verified outcomes")
    add("")
    add("Announcements were SEC 8-K filings that report Item 1.01 and contain \"agreement and plan of merger\". A deal is verified only when a later filing, within %d days, states that the merger or business combination closed, or states that the merger agreement was terminated. The outcome sentence had to come from the 8-K or a press release, not from a copy of the merger agreement. Deals without that sentence stayed out of the scores." % WINDOW_DAYS)
    add("")
    add("Training window for the baseline: %s through %s. Filings examined: %d. Kept for the close rate: %d (%d closed, %d terminated). Unresolved or unconfirmed: %d. Not an original signing: %d. Outcome within %d days: %d. Submission errors: %d. Duplicate filings removed: %d." % (
        TRAIN_START, TRAIN_END, meta["train_stats"]["examined"], len(train), train_closed, len(train) - train_closed,
        meta["train_stats"]["unresolved"], meta["train_stats"]["not_original"], MIN_OUTCOME_DAYS,
        meta["train_stats"]["too_soon"], meta["train_stats"]["errors"], meta["train_stats"].get("duplicates", 0)))
    add("")
    add("Evaluation window: %s through %s. The search stopped once %d original signing filings with a confirmed later outcome were found, or the window ended. Filings examined: %d. Original signings before duplicate removal: %d. Unresolved or unconfirmed: %d. Not an original signing: %d. Outcome within %d days: %d. Submission errors: %d." % (
        EVAL_START, EVAL_END, EVAL_VERIFIED_CAP, meta["eval_stats"]["examined"], meta["eval_stats"]["verified"],
        meta["eval_stats"]["unresolved"], meta["eval_stats"]["not_original"], MIN_OUTCOME_DAYS,
        meta["eval_stats"]["too_soon"], meta["eval_stats"]["errors"]))
    add("")
    add("### Evaluation deals")
    add("")
    if not eval_rows:
        add("No evaluation deal had both a verified outcome and a readable announcement filing.")
        add("")
    else:
        table(
            ["Filer", "Ticker", "Announced", "Outcome", "Outcome date", "Evidence from the outcome filing"],
            [[
                (row.get("filer") or "").replace("|", "/"),
                row.get("ticker") or "—",
                row["announced"],
                "Closed" if row["label"] == 1 else "Terminated",
                row["outcomeDate"],
                (row.get("evidence") or "").replace("|", "/"),
            ] for row in eval_rows],
        )
    add("### Training deals used only for the close rate")
    add("")
    add("These deals fix the baseline probability. Their outcomes are not in the evaluation average.")
    add("")
    if not train:
        add("No training deal was verified, so the baseline close rate was not calculated.")
        add("")
    else:
        table(
            ["Filer", "Ticker", "Announced", "Outcome", "Outcome date"],
            [[
                (row.get("filer") or "").replace("|", "/"),
                row.get("ticker") or "—",
                row["announced"],
                "Closed" if row["label"] == 1 else "Terminated",
                row["outcomeDate"],
            ] for row in train],
        )

    add("## 3. Predicted probabilities")
    add("")
    add("Each probability is `quote.close_probability` on flags from that deal's announcement packet. The call was made on this run. The prediction date for the information used is the announcement filing date, not the run date.")
    add("")
    if not valid:
        add("No evaluation row had both a verified outcome and announcement flags.")
        add("")
    else:
        table(
            ["Ticker", "Announced", "Flags from the announcement", "Predicted close probability", "Outcome"],
            [[
                row.get("ticker") or "—",
                row["announced"],
                flag_summary(row["flags"]).replace("|", "/"),
                "%.4f" % row["probability"],
                "1" if row["label"] == 1 else "0",
            ] for row in valid],
        )
        add("Predicted probabilities ranged from %.4f to %.4f. The mean prediction was %.4f." % (min(probs), max(probs), mean(probs)))
        add("")
        if closed:
            add("Mean prediction on deals that closed: %.4f (n=%d)." % (mean([row["probability"] for row in closed]), len(closed)))
        else:
            add("No scored deal closed.")
        if terminated:
            add("Mean prediction on deals that were terminated: %.4f (n=%d)." % (mean([row["probability"] for row in terminated]), len(terminated)))
        else:
            add("No scored deal was terminated, so the function was not observed on a failed deal in this window.")
        add("")

    add("## 4. Brier scores")
    add("")
    add("Brier score = (predicted probability − outcome)². Closed is 1 and terminated is 0. Lower is better.")
    add("")
    if not valid:
        add("Mean Brier score: not calculated. Valid scored deals: 0.")
        add("")
    else:
        table(
            ["Ticker", "Predicted", "Outcome", "Brier"],
            [[row.get("ticker") or "—", "%.4f" % row["probability"], str(row["label"]), "%.4f" % row["brier"]] for row in valid],
        )
        add("Valid transactions: %d." % len(valid))
        add("Closed: %d of %d (%.1f%%)." % (len(closed), len(valid), pct(len(closed), len(valid))))
        add("Mean predicted probability: %.4f." % mean(probs))
        add("Mean Brier score: %.4f." % model_brier)
        if closed:
            add("Mean Brier on closed deals: %.4f." % mean([row["brier"] for row in closed]))
        if terminated:
            add("Mean Brier on terminated deals: %.4f." % mean([row["brier"] for row in terminated]))
        auc = roc_auc(valid)
        if auc is None:
            add("ROC AUC: not calculated. The scored deals do not include both a closing and a termination.")
        else:
            add("ROC AUC: %.3f. This ranks closed deals against terminated deals. With %d terminated deal%s, the rank is unstable." % (
                auc, len(terminated), "" if len(terminated) == 1 else "s"))
        add("")

    add("## 5. Baseline comparison")
    add("")
    if rate is None:
        add("Baseline: not calculated. The earlier window produced no verified deals, so there is no separate closing rate to compare against. The 0.90 constant inside the function is a judgment, not a rate counted from these filings.")
        add("")
    else:
        add("The baseline predicts %.4f for every evaluation deal. That is the share of verified training deals that closed: %d of %d, announced from %s through %s. It was not computed from the evaluation outcomes." % (
            rate, train_closed, len(train), train[0]["announced"], train[-1]["announced"]))
        add("")
        if base_brier is None:
            add("Baseline Brier score: not calculated, because no evaluation deal was scored.")
        else:
            add("Baseline Brier score on the same evaluation deals: %.4f." % base_brier)
            add("DealRadar mean Brier score: %s." % fmt(model_brier))
            add("Difference (baseline minus DealRadar): %.4f. A positive difference means the filing flags beat a constant prediction at the training close rate." % (base_brier - model_brier))
            if gap:
                add("A 2,000-draw bootstrap of the evaluation deals, with the training rate held fixed, put that difference between %.4f and %.4f (2.5th to 97.5th percentile)." % (gap["low"], gap["high"]))
        add("")
        add("The training rate is the rate among deals whose outcome filing could be confirmed. Deals that never filed a clear closing or termination notice are not in it. It is not the close rate of every announced merger.")
        add("")

    add("## 6. Missing inputs, leakage, and other limits")
    add("")
    add("- Outcome text was not fed into `quote.close_probability`.")
    add("- The training deals and the evaluation deals come from different months. An evaluation company whose CIK already appeared in the training set was skipped.")
    add("- %d examined training filings and %d examined evaluation filings had no confirmed outcome and were left out. They were not labeled as closed." % (
        meta["train_stats"]["unresolved"], meta["eval_stats"]["unresolved"]))
    add("- Amendment filings, and filings that do not say the company entered into a merger agreement, were left out. A later amendment can contain terms that were not in the original announcement.")
    add("- An outcome dated less than %d days after the filing was left out. Those filings were often describing a closing that was already underway." % MIN_OUTCOME_DAYS)
    if excluded:
        add("- Scored-set exclusions:")
        for row in excluded:
            add("  - %s (%s): %s" % (row.get("ticker") or row.get("filer"), row["announced"], row.get("excluded") or "Announcement text was missing, so no probability was calculated."))
    else:
        add("- Every verified evaluation deal produced a probability. None was dropped after scoring.")
    second = [row for row in valid if (row.get("flags") or {}).get("secondRequest")]
    add("- Second-request flag was set on %d scored deal%s. At announcement this phrase is often a condition written into the agreement, not a request the regulator has already made." % (
        len(second), "" if len(second) == 1 else "s"))
    add("- Buyer and target can each file an 8-K for one deal. A later filing that named a party from an earlier filing in the same two-week span was removed from the scored set when the name match was clear.")
    add("- The extractor can miss a flag that is present, or set one from a boilerplate phrase. Scores use the extractor's reading.")
    add("- No `data/model.json` file was used. This test does not load or change a trained model.")
    if meta["git"]["dirty"]:
        if "quote.py" in meta["git"]["dirty"]:
            add("- quote.py differs from git HEAD. The test called that working copy and did not edit it further.")
        else:
            add("- Uncommitted edits exist in %s. quote.py is not one of them." % ", ".join(meta["git"]["dirty"]))
    add("")
    add("### Sources")
    add("")
    for row in eval_rows:
        add("- %s, announced %s. Announcement: %s. Outcome filing %s %s: %s." % (
            row.get("ticker") or row.get("filer"), row["announced"], link(row.get("announcementUrl")),
            row.get("outcomeForm") or "", row["outcomeDate"], link((row.get("outcomeUrls") or [None])[0])))
    add("")

    add("## 7. Does the function show useful calibration?")
    add("")
    if not valid or rate is None or base_brier is None:
        add("No. The filings needed for a separate baseline and a scored evaluation set were not both available, so calibration was not measured.")
    else:
        spread = max(probs) - min(probs)
        level_gap = mean(probs) - pct(len(closed), len(valid)) / 100.0
        add("On these %d deals the function's average prediction was %.4f and the share that closed was %.1f%%. The gap between those two figures is %+.4f." % (
            len(valid), mean(probs), pct(len(closed), len(valid)), level_gap))
        add("")
        add("The probabilities span %.4f points, from %.4f to %.4f. In this sample the filing flags moved the result only a few points around 0.90." % (
            spread, min(probs), max(probs)))
        add("")
        if terminated:
            add("Terminated deals were predicted at %.4f on average, against %.4f for deals that closed." % (
                mean([row["probability"] for row in terminated]), mean([row["probability"] for row in closed]) if closed else float("nan")))
            add("")
        better = gap and gap["low"] > 0
        worse = gap and gap["high"] < 0
        if preliminary:
            add("The sample is too small for a stable conclusion, particularly because terminated deals are scarce. Treat every comparison below as preliminary.")
            add("")
        if better:
            add("The filing flags beat the training close rate on this sample. The bootstrap interval for the Brier improvement stays above zero.")
        elif worse:
            add("The filing flags were worse than predicting the training close rate on this sample. The bootstrap interval for the Brier difference stays below zero.")
        else:
            add("This sample does not show that the filing flags improve on the training close rate. The bootstrap interval for the Brier difference includes zero.")
        add("")
        if spread < 0.08:
            add("Useful calibration would require probabilities that move when the chance of closing moves. Here most of the number is the fixed 0.90 starting point. The flags do not separate completed deals from terminated deals by enough to be a useful close-probability estimate on this sample.")
        elif terminated and closed and mean([row["probability"] for row in terminated]) >= mean([row["probability"] for row in closed]) - 0.02:
            add("The terminated deals did not receive meaningfully lower probabilities than the deals that closed. The function is not distinguishing the two outcomes in this sample.")
    add("")
    path = REPORT
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return {
        "valid": len(valid),
        "closed": len(closed),
        "terminated": len(terminated),
        "train": len(train),
        "train_rate": rate,
        "mean_prediction": mean(probs) if probs else None,
        "model_brier": model_brier,
        "base_brier": base_brier,
        "gap": gap,
        "preliminary": preliminary,
        "report": path,
    }


def main():
    ensure_dirs()
    if not server.EDGAR_UA:
        print("EDGAR_USER_AGENT is missing. The SEC request was not sent.")
        return 1
    formula = formula_checks()
    print("formula check ok, blank probability %.4f" % formula[0][1])
    train_all, train_stats = collect("train", TRAIN_START, TRAIN_END, TRAIN_VERIFIED_CAP, TRAIN_EXAMINED_CAP, set())
    train = drop_duplicate_transactions(train_all)
    train_stats["duplicates"] = sum(1 for row in train_all if row.get("excluded"))
    blocked = {row["cik"] for row in train_all}
    eval_rows, eval_stats = collect("eval", EVAL_START, EVAL_END, EVAL_VERIFIED_CAP, EVAL_EXAMINED_CAP, blocked)
    for row in eval_rows:
        text, payload = announcement_text(row)
        if not text:
            row["excluded"] = payload.get("error") or "The announcement filing had no readable text."
            row["probability"] = None
            continue
        extracted = terms.extract_terms(text)
        flags, scored = score_flags(extracted)
        row["flags"] = {
            "hsr": bool(flags.get("hsr")),
            "secondRequest": bool(flags.get("secondRequest")),
            "foreign": flags.get("foreign") or [],
            "other": flags.get("other") or [],
            "financingCondition": flags.get("financingCondition"),
            "tender": bool(flags.get("tender")),
            "vote": bool(flags.get("vote")),
            "goShop": bool(flags.get("goShop")),
            "consideration": flags.get("consideration"),
        }
        row["parent"] = extracted.get("parent")
        row["company"] = extracted.get("company")
        row["probability"] = scored["close"]
        row["brier"] = brier(scored["close"], row["label"])
        row["sources"] = payload.get("sources") or []
        print("  scored %s p=%.4f y=%s" % (row.get("ticker") or row["filer"], row["probability"], row["label"]))
    kept = drop_duplicate_transactions([row for row in eval_rows if row.get("probability") is not None])
    kept_ids = {row["adsh"] for row in kept}
    for row in eval_rows:
        if row.get("probability") is not None and row["adsh"] not in kept_ids:
            row["probability_dropped"] = row["probability"]
            row["probability"] = None
            row["brier"] = None
    summary = build_report({
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "git": git_info(),
        "formula": formula,
        "train": train,
        "eval": eval_rows,
        "train_stats": train_stats,
        "eval_stats": eval_stats,
    })
    with open(os.path.join(CACHE, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump({k: summary[k] for k in summary if k != "gap"}, handle, indent=2)
        handle.write("\n")
    print("valid %s closed %s terminated %s train %s" % (
        summary["valid"], summary["closed"], summary["terminated"], summary["train"]))
    print("mean_prediction %s model_brier %s base_brier %s train_rate %s" % (
        summary["mean_prediction"], summary["model_brier"], summary["base_brier"], summary["train_rate"]))
    print("bootstrap %s" % summary["gap"])
    print("preliminary %s" % summary["preliminary"])
    print("report %s" % summary["report"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
