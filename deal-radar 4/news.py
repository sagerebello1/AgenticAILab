"""Live headlines from Yahoo Finance, turned into a bounded nudge to the deal's odds.

Source: the public RSS headline feed for a ticker (feeds.finance.yahoo.com). Yahoo does not offer a
documented API for this, so the feed can change or rate-limit without notice. Use is for personal
research; read Yahoo's terms before building anything on top of it.

How a headline moves the odds. Each headline is matched against the rules below. A rule has a
weight in log-odds (negative makes the deal less likely to close). Newer headlines count more
(half-life 10 days), and the total is capped at +/-1.5 so one noisy day cannot overwhelm what the
trained model learned from the filing. IMPORTANT: these weights are hand-set judgments. They were
not trained, because there is no historical headline dataset behind this project. Treat the
adjustment as a transparent heuristic and check the headlines it shows.
"""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEED = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
UA = "Mozilla/5.0 (compatible; DealRadar research prototype)"
HALF_LIFE_DAYS = 10.0
CAP = 1.5            # most the news can move the odds, in log-odds points
CAP_DECISIVE = 4.0   # when a headline says the deal ended or completed, news may move them much further

# (pattern, weight in log-odds, tag shown to the user)
RULES = [
    (r"terminat(?:es|ed|ion of)\s+(?:the\s+|its\s+)?(?:merger|deal|acquisition|agreement)|calls?\s+off|walks?\s+away|scrap(?:s|ped)\s+(?:the\s+)?(?:deal|merger|acquisition)|abandon(?:s|ed)\s+(?:the\s+)?(?:deal|merger|acquisition)", -2.5, "Deal ended"),
    (r"(?:ftc|doj|justice department|regulators?|cma|european commission)\s+(?:sues?|suing|challenges?|moves? to block|blocks?|blocked)|antitrust\s+(?:lawsuit|suit)|sues? to block", -1.3, "Regulator challenge"),
    (r"second\s+request", -0.5, "Second request"),
    (r"phase\s+(?:2|ii)|in-depth\s+(?:investigation|probe|review)", -0.5, "Deep regulatory review"),
    (r"(?:iss|glass lewis)\s+(?:recommends?\s+)?(?:against|opposes)|shareholders?\s+(?:oppose|reject|push back|vote against)|activist.*oppos", -0.8, "Holder opposition"),
    (r"financing\s+(?:concerns?|doubts?|trouble|problems?)|(?:lenders?|banks?)\s+(?:balk|pull)", -0.8, "Financing concern"),
    (r"delay(?:s|ed)?\s+(?:the\s+)?(?:deal|merger|closing|acquisition)|extends?\s+(?:the\s+)?(?:outside date|tender offer)", -0.3, "Delay"),
    (r"(?:receives?|received|secures?|secured|obtains?|obtained|wins?|won|gets?|got)\s+(?:all\s+|final\s+)?(?:regulatory|antitrust|hsr|cfius|eu|european|china)\s+(?:approval|clearance)|(?:cleared|approved)\s+by\s+(?:the\s+)?(?:ftc|doj|european commission|cfius|samr|cma)", 0.6, "Approval received"),
    (r"waiting\s+period\s+(?:has\s+)?(?:expired|expires|ends)|early\s+termination", 0.5, "HSR waiting period ended"),
    (r"(?:shareholders?|stockholders?)\s+(?:approve|approved|vote\s+(?:in\s+favor|to\s+approve))|approved\s+by\s+(?:its\s+)?(?:shareholders?|stockholders?)", 0.7, "Holders approved"),
    (r"tender\s+offer\s+(?:expired|completed|successful|extended)|(?:majority|most)\s+of\s+shares\s+tendered", 0.8, "Tender progress"),
    (r"(?:completes?|completed|closes?|closed|finalizes?|finalized)\s+(?:its\s+|the\s+)?(?:acquisition|merger|deal|takeover)", 1.5, "Deal completed"),
]
COMPILED = [(re.compile(rx, re.I), w, tag) for rx, w, tag in RULES]
RIVAL = re.compile(r"rival\s+bid|competing\s+(?:bid|offer)|topping\s+bid|counter-?offer|sweeten(?:s|ed)|raises?\s+(?:its\s+)?(?:offer|bid)|higher\s+offer|bidding\s+war", re.I)
DEAL_WORDS = re.compile(r"merger|acqui|takeover|buyout|deal|tender offer|to be bought|bid|antitrust|regulator|ftc|doj|cfius", re.I)


class NewsError(Exception):
    pass


def fetch(ticker, timeout=12):
    url = FEED % urllib.parse.quote(ticker)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            root = ET.fromstring(r.read())
    except (urllib.error.URLError, ET.ParseError) as e:
        raise NewsError("Could not read the Yahoo Finance feed: %s" % e)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        when = None
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            pass
        items.append({"title": title, "link": (it.findtext("link") or "").strip(), "published": when, "source": "Yahoo Finance"})
    return items


def score(items, names=(), now=None):
    """Return {adjustment, headlines, flags}. `names` are company names that make a headline relevant."""
    now = now or datetime.now(timezone.utc)
    name_rx = re.compile("|".join(re.escape(n.split()[0]) for n in names if n), re.I) if any(names) else None
    total, rows, rival = 0.0, [], False
    for it in items:
        title = it["title"]
        relevant = bool(DEAL_WORDS.search(title)) or bool(name_rx and name_rx.search(title))
        if not relevant:
            continue
        age = max(0.0, (now - it["published"]).total_seconds() / 86400) if it["published"] else 30.0
        decay = 0.5 ** (age / HALF_LIFE_DAYS)
        tags, w = [], 0.0
        for rx, weight, tag in COMPILED:
            if rx.search(title):
                tags.append(tag)
                w += weight
        if RIVAL.search(title):
            rival = True
            tags.append("Rival bid or higher offer")
        total += w * decay
        rows.append({"title": title, "link": it["link"], "published": it["published"].isoformat() if it["published"] else None,
                     "tags": tags, "weight": round(w, 2), "age_days": round(age, 1)})
    ended = any("Deal ended" in r["tags"] for r in rows)
    completed = any("Deal completed" in r["tags"] for r in rows)
    cap = CAP_DECISIVE if (ended or completed) else CAP
    adj = max(-cap, min(cap, total))
    rows.sort(key=lambda r: r["age_days"])
    return {"adjustment": round(adj, 3), "headlines": rows[:12], "flags": {"rivalBid": rival, "ended": ended, "completed": completed}}


def apply(p, adjustment):
    """Shift a probability by an adjustment in log-odds."""
    p = min(0.999, max(0.001, p))
    z = math.log(p / (1 - p)) + adjustment
    return 1 / (1 + math.exp(-z))


def finnhub_items(ticker, key, days=14, timeout=12):
    """Company headlines from Finnhub (needs the free API key). Same shape as fetch()."""
    from datetime import date, timedelta
    end = date.today()
    q = urllib.parse.urlencode({"symbol": ticker, "from": (end - timedelta(days=days)).isoformat(), "to": end.isoformat()})
    req = urllib.request.Request("https://finnhub.io/api/v1/company-news?" + q, headers={"User-Agent": UA, "X-Finnhub-Token": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, ValueError) as e:
        raise NewsError("Could not read Finnhub news: %s" % e)
    out = []
    for it in data if isinstance(data, list) else []:
        title = (it.get("headline") or "").strip()
        if not title:
            continue
        ts = it.get("datetime")
        out.append({"title": title, "link": it.get("url") or "", "source": ((it.get("source") or "") + " via Finnhub").strip(),
                    "published": datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None})
    return out


def for_ticker(ticker, names=(), finnhub_key=""):
    items, errs, used = [], [], []
    try:
        items = fetch(ticker)
        used.append("Yahoo Finance")
    except NewsError as e:
        errs.append(str(e))
    if finnhub_key:
        try:
            seen = {i["title"].lower() for i in items}
            items += [i for i in finnhub_items(ticker, finnhub_key) if i["title"].lower() not in seen]
            used.append("Finnhub")
        except NewsError as e:
            errs.append(str(e))
    if not items and errs:
        raise NewsError(" ".join(errs))
    out = score(items, names)
    out["sources"] = used
    # Raw headlines too, so the interface can score them together with any the user pastes in
    out["items"] = [{"title": i["title"], "link": i["link"], "source": i.get("source"), "published": i["published"].isoformat() if i["published"] else None} for i in items]
    return out


def config():
    """The scoring rules as plain data, so the interface can apply the very same rules to pasted headlines."""
    return {"halfLife": HALF_LIFE_DAYS, "cap": CAP, "capDecisive": CAP_DECISIVE,
            "rules": [[rx, w, tag] for rx, w, tag in RULES], "rival": RIVAL.pattern, "dealWords": DEAL_WORDS.pattern}
