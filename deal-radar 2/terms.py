"""Turns the text of an SEC filing into deal terms, and terms into a close probability.

This is the rules half of the agent. It reads an 8-K or tender offer filing, pulls out the
offer price, form of payment, expected close and the conditions that decide whether the deal
gets done, and keeps the sentence each fact came from so a person can check it.
llm.py can replace the extraction step when an Anthropic key is configured; the probability
rules below are always applied afterwards, so the two paths score deals the same way.
"""
import html
import re
from datetime import date, timedelta

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"])}
QUARTER_END = {"first": (3, 31), "second": (6, 30), "third": (9, 30), "fourth": (12, 31)}
HALF_END = {"first": (6, 30), "second": (12, 31)}

PRICE_RE = re.compile(
    r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+(?:in\s+cash\s*,?\s*(?:without\s+interest\s*,?\s*)?)?per\s+share", re.I)
PAR_OR_ISSUE_RE = re.compile(r"par\s+value|issue\s+price", re.I)
CLOSE_Q_RE = re.compile(
    r"(?:expected|anticipated)\s+to\s+(?:close|be\s+completed|be\s+consummated|occur)\s+"
    r"(?:in|during|by|before|on\s+or\s+before)?\s*(?:the\s+)?(first|second|third|fourth)\s+(quarter|half)"
    r"\s+of\s+(?:calendar\s+|fiscal\s+)?(?:year\s+)?(20\d\d)", re.I)
CLOSE_M_RE = re.compile(
    r"(?:expected|anticipated)\s+to\s+(?:close|be\s+completed|be\s+consummated|occur)\s+"
    r"(?:in|during|by|before|on\s+or\s+before)?\s*(?:the\s+)?(?:end\s+of\s+)?(january|february|march|april|may|june|july|"
    r"august|september|october|november|december)\s+(20\d\d)", re.I)
CLOSE_Y_RE = re.compile(
    r"(?:expected|anticipated)\s+to\s+(?:close|be\s+completed|be\s+consummated)\s+(?:by\s+)?(?:the\s+)?end\s+of\s+"
    r"(?:calendar\s+|fiscal\s+)?(?:year\s+)?(20\d\d)", re.I)
PARENT_RE = re.compile(
    r"by\s+and\s+(?:among|between)\s+(.{3,120}?)\s*,?\s*\(\s*(?:the\s+)?[\"“”']?(?:Parent|Acquirer|Buyer|Purchaser)[\"“”']?\s*\)", re.I)
COMPANY_RE = re.compile(
    r"(?:,|and)\s+([A-Z][^()]{3,120}?)\s*,?\s*\(\s*(?:the\s+)?[\"“”']?Company[\"“”']?\s*\)")
FEE_RE = re.compile(
    r"termination\s+fee\s+(?:of|equal\s+to|in\s+the\s+amount\s+of)\s+(?:approximately\s+)?\$\s?([\d,.]+)\s*(million|billion)?", re.I)

FOREIGN = [
    ("CFIUS", re.compile(r"\bCFIUS\b|Committee\s+on\s+Foreign\s+Investment", re.I)),
    ("China SAMR", re.compile(r"\bSAMR\b|State\s+Administration\s+for\s+Market\s+Regulation", re.I)),
    ("European Commission", re.compile(r"European\s+Commission|EU\s+Merger\s+Regulation", re.I)),
    ("UK CMA", re.compile(r"Competition\s+and\s+Markets\s+Authority|\bCMA\b")),
]
OTHER_APPROVALS = [
    ("State utility commission", re.compile(r"public\s+(?:utility|service)\s+commission|utilities\s+commission", re.I)),
    ("FCC", re.compile(r"Federal\s+Communications\s+Commission|\bFCC\b")),
    ("Bank regulators", re.compile(r"Federal\s+Reserve|\bOCC\b|\bFDIC\b", re.I)),
]


def to_text(raw):
    """Strip an HTML filing down to plain text."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    for _ in range(3):
        nxt = html.unescape(raw)
        if nxt == raw:
            break
        raw = nxt
    raw = raw.replace("\xa0", " ")
    return re.sub(r"\s+", " ", raw).strip()


def _snip(text, m, width=120):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("..." if a else "") + text[a:b].strip() + ("..." if b < len(text) else "")


def _close_date(text):
    """Return (iso date, phrase) for the expected closing date, or (None, None)."""
    m = CLOSE_Q_RE.search(text)
    if m:
        which, unit, year = m.group(1).lower(), m.group(2).lower(), int(m.group(3))
        mo, d = (QUARTER_END if unit == "quarter" else HALF_END).get(which, (None, None))
        if mo:
            return date(year, mo, d).isoformat(), _snip(text, m, 40)
    m = CLOSE_M_RE.search(text)
    if m:
        mo, year = MONTHS[m.group(1).lower()], int(m.group(2))
        nxt = date(year + (mo == 12), mo % 12 + 1, 1)
        return (nxt - timedelta(days=1)).isoformat(), _snip(text, m, 40)
    m = CLOSE_Y_RE.search(text)
    if m:
        return date(int(m.group(1)), 12, 31).isoformat(), _snip(text, m, 40)
    return None, None


def offer_mentions(text):
    """Cash-style per-share prices, skipping par value and a buyer's stock issue price.

    Each item is (price, sentence, mentioned_with_cash).
    """
    found = []
    for m in PRICE_RE.finditer(text or ""):
        price = float(m.group(1))
        if not (0.5 <= price <= 5000):
            continue
        prefix = text[max(0, m.start() - 24):m.start()]
        if PAR_OR_ISSUE_RE.search(prefix):
            continue
        window = text[max(0, m.start() - 40):m.end() + 40]
        found.append((price, _snip(text, m), bool(re.search(r"in\s+cash", window, re.I))))
    return found


def best_offer(text):
    """Return (price, sentence) or (None, None). A price said to be in cash wins."""
    mentions = offer_mentions(text)
    pool = [m for m in mentions if m[2]] or mentions
    if not pool:
        return None, None
    prices = [p for p, _, _ in pool]
    price = max(set(prices), key=lambda p: (prices.count(p), -prices.index(p)))
    sentence = next(s for p, s, _ in pool if p == price)
    return price, sentence


def filing_status(text, offer, download_error, had_document):
    """One of retrieval_failed, parsing_failed, no_relevant_filing, terms_need_verification, extracted."""
    if download_error and not (text or "").strip():
        return "retrieval_failed", "The SEC filing could not be downloaded. " + download_error
    if not had_document:
        return "no_relevant_filing", "No merger filing document was attached to this search hit."
    if not (text or "").strip():
        return "parsing_failed", "The filing downloaded, but no readable text was found."
    if offer is None:
        return "terms_need_verification", explain_missing_offer(text)
    return "extracted", ""


def explain_missing_offer(text):
    """Why a read filing still has no cash price per share. The wording comes from the text."""
    body = text or ""
    if re.search(r"mutually terminate|terminate the merger agreement|termination agreement", body, re.I):
        return "This filing ends a merger agreement. It does not state a new cash price per share."
    if re.search(r"completed its previously announced merger|completion of acquisition or disposition", body, re.I):
        return "This filing reports that a merger has already closed. It does not restate a cash price per share."
    if re.search(r"purchase price of\s+\$[\d,.]+\s+billion|\$[\d,.]+\s+million(?:\s+\w+){0,3}\s+purchase price", body, re.I):
        return "The filing states a purchase price for another company, not a cash price per share of this stock."
    if re.search(r"amendment(?:\s+no\.?\s*\d+)?\s+to\s+(?:the\s+)?agreement and plan of merger|merger agreement amendment", body, re.I):
        return "This filing amends an earlier merger agreement and does not restate a cash price per share."
    if re.search(r"stock consideration", body, re.I):
        return "The filing describes stock consideration and does not state a cash price per share for this company."
    return "A merger filing was found and read. It does not state a cash price per share for this stock."


def extract_terms(text):
    """Pull deal terms out of filing text. Every fact keeps the sentence it came from."""
    out = {"offer": None, "consideration": None, "expectedClose": None, "closePhrase": None,
           "parent": None, "company": None, "evidence": {}, "flags": {}}

    offer, sentence = best_offer(text)
    if offer is not None:
        out["offer"] = offer
        out["evidence"]["offer"] = sentence

    cash = bool(re.search(r"\bin\s+cash\b|cash\s+consideration|all[- ]cash", text, re.I))
    stock = bool(re.search(r"exchange\s+ratio|shares\s+of\s+(?:Parent|Acquirer|Buyer)\s+common\s+stock", text, re.I))
    out["consideration"] = "mixed" if cash and stock else "stock" if stock else "cash" if cash else None

    out["expectedClose"], out["closePhrase"] = _close_date(text)

    m = PARENT_RE.search(text)
    if m:
        out["parent"] = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
    m = COMPANY_RE.search(text)
    if m:
        name = re.sub(r"\s+", " ", m.group(1))
        if " and " in name:                     # "Merger Sub Inc. and Marrow, Inc." -> keep the last party
            name = name.rsplit(" and ", 1)[1]
        out["company"] = name.strip(" ,.")

    flags = out["flags"]
    flags["hsr"] = bool(re.search(r"Hart[- ]Scott[- ]Rodino|\bHSR\b", text, re.I))
    m = re.search(r"second\s+request", text, re.I)
    flags["secondRequest"] = bool(m)
    if m:
        out["evidence"]["secondRequest"] = _snip(text, m)
    flags["foreign"] = [name for name, rx in FOREIGN if rx.search(text)]
    flags["other"] = [name for name, rx in OTHER_APPROVALS if rx.search(text)]
    if re.search(r"not\s+(?:subject\s+to|conditioned\s+(?:up)?on)\s+(?:any\s+)?(?:a\s+)?financing", text, re.I) \
            or re.search(r"no\s+financing\s+condition", text, re.I):
        flags["financingCondition"] = False
    elif re.search(r"financing\s+condition|conditioned\s+(?:up)?on\s+(?:the\s+)?(?:receipt\s+of\s+)?financing", text, re.I):
        flags["financingCondition"] = True
    else:
        flags["financingCondition"] = None
    flags["tender"] = bool(re.search(r"tender\s+offer", text, re.I))
    flags["vote"] = bool(re.search(
        r"(?:stockholder|shareholder)\s+(?:approval|vote)|vote\s+of\s+(?:the\s+)?(?:stockholders|shareholders)"
        r"|approval\s+(?:of|by)\s+(?:the\s+)?(?:company'?s?\s+)?(?:stockholders|shareholders)", text, re.I))
    flags["goShop"] = bool(re.search(r"go[- ]shop", text, re.I))
    fees = []
    for m in FEE_RE.finditer(text):
        unit = (m.group(2) or "").lower()
        fees.append("$" + m.group(1).rstrip(".,") + (" " + unit if unit else ""))
    flags["termFees"] = fees[:3]
    return out


def estimate_probabilities(consideration, flags):
    """Chance the deal eventually closes, with each factor that moved it.

    These are judgment-based starting points, not a fitted model. The interface lets the user
    override every number. Returns (p_close, p_pending, drivers).
    """
    p = 0.93
    drivers = [{"label": "Typical announced deal", "delta": 0.0, "note": "Starting point: most announced public deals close."}]

    def add(label, delta, note=""):
        nonlocal p
        p += delta
        drivers.append({"label": label, "delta": delta, "note": note})

    if flags.get("hsr"):
        add("US antitrust clearance (HSR)", -0.01, "Routine filing, rarely blocks a deal on its own.")
    if flags.get("secondRequest"):
        add("Second request from antitrust regulators", -0.10, "A deeper review. Raises delay and block risk.")
    foreign = flags.get("foreign") or []
    if foreign:
        add("Foreign approvals: " + ", ".join(foreign), -min(0.03 * len(foreign), 0.09), "Each extra regulator adds timing and veto risk.")
    other = flags.get("other") or []
    if other:
        add("Sector approvals: " + ", ".join(other), -min(0.03 * len(other), 0.06), "Industry regulators can add conditions or delay.")
    fin = flags.get("financingCondition")
    if fin is True:
        add("Deal depends on financing", -0.06, "If the buyer cannot raise the money the deal can fall away.")
    elif fin is False:
        add("No financing condition", 0.01, "The buyer has to close even if its financing is late.")
    if flags.get("tender"):
        add("Tender offer", 0.02, "Shareholders sell directly, so there is no meeting to wait for.")
    elif flags.get("vote"):
        add("Shareholder vote required", -0.01, "A vote can fail, though most pass.")
    if flags.get("goShop"):
        add("Go-shop period", -0.01, "A rival may bid higher, which can pay a call holder but ends this deal.")
    if consideration == "stock":
        add("Paid in acquirer stock", -0.02, "The value of the offer moves with the buyer's share price.")
    p = min(0.98, max(0.35, p))
    p_pending = min(0.97, max(0.2, p - 0.06))
    return round(p, 3), round(p_pending, 3), drivers
