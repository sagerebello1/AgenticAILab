"""Read a merger filing. Labels and prices come only from sentences in that filing."""
import html
import re

import terms

TAG_RE = re.compile(r"<[^>]+>")
SYMBOL_TAG_RE = re.compile(r'name="dei:TradingSymbol"[^>]*>([A-Z][A-Z0-9.\-]{0,5})<', re.I)
CIK_TAG_RE = re.compile(r'scheme="http://www.sec.gov/CIK">0*(\d+)<', re.I)
STOP = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "llc", "lp",
    "the", "and", "of", "group", "holdings", "trust", "reit", "plc", "sa", "nv",
}


def plain_text(raw):
    """Visible text with tags and HTML entities removed."""
    text = raw or ""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = html.unescape(text)
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    text = TAG_RE.sub(" ", text)
    return " ".join(text.split())


def _tokens(name):
    return {tok for tok in re.findall(r"[a-z0-9]+", (name or "").lower()) if tok not in STOP and len(tok) > 1}


def _overlaps(left, right):
    return bool(_tokens(left) & _tokens(right))


def _definition_window(section, label):
    marker = re.search(r'\(\s*(?:the\s+)?"\s*%s\s*"' % label, section)
    if not marker:
        return ""
    return section[max(0, marker.start() - 220):marker.start()]


def _defined_name(section, label):
    """Legal name that the filing defines as Company or Parent."""
    window = _definition_window(section, label)
    if not window:
        return None
    window = re.sub(r"\b(Inc|Corp|Co|Ltd)\.", r"\1", window)
    window = re.split(r",\s+a\s+[A-Z]", window)[0]
    parts = [part.strip(" ,") for part in window.split(".") if part.strip(" ,")]
    clause = parts[-1] if parts else window
    return " ".join(clause.split()).strip(" ,") or None


def _section(plain):
    low = plain.lower()
    start = low.find("item 1.01")
    if start < 0:
        return "", ""
    clip = plain[start:start + 5000]
    return clip, clip.lower()


def _into_party(head):
    match = re.search(
        r"merge[ds]? with and into (the company|[a-z0-9][a-z0-9&.'\- ]{0,40}?)"
        r"(?=\s*(?:\(|,| with| as| and|$))",
        head,
    )
    if not match:
        return None
    return " ".join(match.group(1).split())


def _is_filer(party, filer, company_alias, section):
    if party in ("the company", "company"):
        if company_alias and _overlaps(filer, company_alias):
            return True
        return _overlaps(filer, _definition_window(section, "Company"))
    return _overlaps(party, filer)


def classify_role(raw, filer_name):
    """target, buyer, not_merger, or unclear. The reason is a short label, not a probability."""
    plain = plain_text(raw)
    section, head = _section(plain)
    if not head:
        return "unclear", "empty filing"
    merger_language = any(phrase in head for phrase in (
        "agreement and plan of merger",
        "agreement and plan of reorganization",
        "merge with and into",
        "merged with and into",
        "tender offer",
    ))
    if not merger_language:
        return "not_merger", "item 1.01 does not describe a merger or tender"
    company_alias = _defined_name(section, "Company")
    party = _into_party(head)
    if party and _is_filer(party, filer_name, company_alias, section):
        return "target", "merger is into the filing company"
    if party and not _is_filer(party, filer_name, company_alias, section):
        filer_tokens = _tokens(filer_name)
        owns_sub = any(("subsidiary of " + tok) in head for tok in filer_tokens)
        if owns_sub or ("subsidiary of the company" in head and _overlaps(filer_name, company_alias or "")):
            return "buyer", "filing company is acquiring the other party"
    tender = "tender offer" in head or "offer to purchase" in head
    if tender and company_alias and _overlaps(filer_name, company_alias) and "outstanding" in head:
        return "target", "tender offer for the filing company"
    for tok in _tokens(filer_name):
        if tender and ("of %s" % tok) in head and "outstanding" in head:
            return "target", "tender offer for the filing company's shares"
    if company_alias and _overlaps(filer_name, company_alias):
        for tok in _tokens(company_alias):
            if ("acquisition of %s" % tok) in head:
                return "target", "filing states an acquisition of the filing company"
    if party:
        return "unclear", "could not match the surviving company to the filer"
    return "unclear", "merger language without a clear surviving company"


def trading_symbol(raw):
    tagged = SYMBOL_TAG_RE.findall(raw or "")
    if tagged:
        return tagged[0].upper()
    return None


def registrant_cik(raw):
    match = CIK_TAG_RE.search(raw or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _offer_clause(sentence, price):
    low = (sentence or "").lower()
    at = -1
    for form in ("%.2f" % price, "%g" % price):
        at = low.find(form)
        if at >= 0:
            break
    if at < 0:
        return low
    return low[max(0, at - 40):at + 90]


def _reject_offer(sentence, price):
    clause = _offer_clause(sentence, price)
    if "per share" not in clause:
        return True
    if "cash" not in clause and "offer price" not in clause:
        return True
    blocked = ("dividend", "not in excess", "exercise price", "liquidation preference")
    return any(phrase in clause for phrase in blocked)


def cash_offer(raw):
    """Cash per-share price, or (None, None) when the sentence is not an offer."""
    text = plain_text(raw)
    price, sentence = terms.best_offer(text)
    if price is None or _reject_offer(sentence, price):
        return None, None
    return float(price), " ".join(sentence.split())[:400]


def exchange_ratio(raw):
    head = _section(plain_text(raw))[1]
    match = re.search(r"exchange ratio(?: of| equal to| is)?\s*(\d+\.\d+|\d+)", head)
    if not match:
        match = re.search(r"(\d+\.\d+)\s*\([^)]{0,90}exchange ratio", head)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def consideration(offer, ratio):
    if offer is not None and ratio is not None:
        return "mixed"
    if offer is not None:
        return "cash"
    if ratio is not None:
        return "stock"
    return None


def acquirer_name(raw):
    section = _section(plain_text(raw))[0]
    name = _defined_name(section, "Parent")
    if not name:
        return None
    return name.strip(" ,.")[:120] or None


def acquirer_ticker(raw):
    """Ticker only when the filing prints an exchange code next to it."""
    head = _section(plain_text(raw))[0]
    match = re.search(r"\b(?:Nasdaq|NYSE|NYSE American)[\s:]+([A-Z][A-Z0-9.\-]{0,5})\b", head)
    if not match:
        return None
    return match.group(1).upper()


def transaction_value(raw):
    """Deal size from a nearby sentence, or (None, None)."""
    head = _section(plain_text(raw))[0]
    match = re.search(
        r"(?i)(equity value|enterprise value|aggregate (?:cash )?consideration|transaction value)"
        r".{0,90}?\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)?",
        head,
    )
    if not match:
        return None, None
    sentence = " ".join(match.group(0).split())[:400]
    number = float(match.group(2).replace(",", ""))
    unit = (match.group(3) or "").lower()
    if unit == "billion":
        number *= 1_000_000_000
    elif unit == "million":
        number *= 1_000_000
    elif number < 1_000_000:
        return None, sentence
    return number, sentence


def count_as_target(role, filer):
    """A listed acquisition company that survives a combination is not the target."""
    if role == "target" and re.search(r"\bacquisition\s+corp", filer or "", re.I):
        return "spac_vehicle"
    return role


def read_filing(raw, filer_name):
    offer, offer_sentence = cash_offer(raw)
    ratio = exchange_ratio(raw)
    value, value_sentence = transaction_value(raw)
    role, reason = classify_role(raw, filer_name)
    role = count_as_target(role, filer_name)
    if role == "spac_vehicle":
        reason = "acquisition-company filer is not counted as a target"
    return {
        "role": role,
        "roleReason": reason,
        "ticker": trading_symbol(raw),
        "registrantCik": registrant_cik(raw),
        "offer": offer,
        "offerSentence": offer_sentence,
        "exchangeRatio": ratio,
        "consideration": consideration(offer, ratio),
        "acquirerName": acquirer_name(raw),
        "acquirerTicker": acquirer_ticker(raw),
        "transactionValue": value,
        "transactionValueSentence": value_sentence,
    }
