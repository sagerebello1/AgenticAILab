"""SEC EDGAR connector.

Uses two public SEC services, neither of which needs an API key:

  * EDGAR full-text search  (efts.sec.gov/LATEST/search-index) to find recent filings that
    contain merger-agreement language. This endpoint powers the search box on sec.gov. The SEC
    does not publish formal documentation for it, so its response format could change.
  * The filing documents themselves under www.sec.gov/Archives/edgar/data/...

The SEC asks every automated client to identify itself with a User-Agent that names the
requester and gives a contact email, and to stay under 10 requests per second. Set
EDGAR_USER_AGENT in .env, for example "Your Name your.email@school.edu". This module also
spaces requests out so it stays well under the limit.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_last_request = [0.0]


class EdgarError(Exception):
    pass


def _get(url, user_agent, max_bytes=1_500_000, timeout=20):
    wait = 0.12 - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes)
    except urllib.error.HTTPError as e:
        raise EdgarError("SEC returned HTTP %d for %s" % (e.code, url))
    except urllib.error.URLError as e:
        raise EdgarError("Could not reach the SEC: %s" % e.reason)
    finally:
        _last_request[0] = time.time()
    return data


NAME_RE = re.compile(r"^(.*?)\s*(?:\(([A-Z][A-Z.\-]{0,5})(?:,\s*[A-Z.\-]+)*\))?\s*\(CIK\s+(\d+)\)")


def _parse_name(display):
    m = NAME_RE.match(display or "")
    if not m:
        return (display or "").strip(), None, None
    return m.group(1).strip(" ,"), m.group(2), m.group(3)


def search_filings(user_agent, days=30, query='"agreement and plan of merger"', forms="8-K", size=40):
    """Return one record per filing that matched, newest first."""
    end = date.today()
    start = end - timedelta(days=days)
    params = {
        "q": query, "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
        "forms": forms,
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    payload = json.loads(_get(url, user_agent))
    seen, out = set(), []
    for hit in payload.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        adsh = src.get("adsh")
        if not adsh or adsh in seen:
            continue
        seen.add(adsh)
        names = [_parse_name(n) for n in src.get("display_names", [])]
        name, ticker, cik = names[0] if names else (None, None, None)
        cik = cik or (src.get("ciks") or [None])[0]
        if not cik:
            continue
        cik_int = int(cik)
        nodash = adsh.replace("-", "")
        filename = hit.get("_id", "").split(":", 1)[1] if ":" in hit.get("_id", "") else None
        out.append({
            "adsh": adsh, "cik": cik_int, "filer": name, "ticker": ticker, "form": src.get("form") or src.get("file_type"),
            "filedOn": src.get("file_date"), "items": src.get("items") or [],
            "indexUrl": "%s/%d/%s/%s-index.htm" % (ARCHIVES, cik_int, nodash, adsh),
            "docUrl": ("%s/%d/%s/%s" % (ARCHIVES, cik_int, nodash, filename)) if filename else None,
        })
    out.sort(key=lambda r: r["filedOn"] or "", reverse=True)
    return out


def fetch_document(user_agent, url, max_bytes=1_500_000):
    return _get(url, user_agent, max_bytes=max_bytes)


def _records(payload):
    seen, out = set(), []
    for hit in payload.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        adsh = src.get("adsh")
        if not adsh or adsh in seen:
            continue
        seen.add(adsh)
        names = [_parse_name(n) for n in src.get("display_names", [])]
        name, ticker, cik = names[0] if names else (None, None, None)
        cik = cik or (src.get("ciks") or [None])[0]
        if not cik:
            continue
        cik_int = int(cik)
        nodash = adsh.replace("-", "")
        filename = hit.get("_id", "").split(":", 1)[1] if ":" in hit.get("_id", "") else None
        out.append({
            "adsh": adsh, "cik": cik_int, "filer": name, "ticker": ticker, "form": src.get("form") or src.get("file_type"),
            "filedOn": src.get("file_date"), "items": src.get("items") or [],
            "docUrl": ("%s/%d/%s/%s" % (ARCHIVES, cik_int, nodash, filename)) if filename else None,
        })
    return out


def search_window(user_agent, start, end, query='"agreement and plan of merger"', forms="8-K", offset=0):
    """One page (up to 100 hits) of full-text results for a date window. Returns (records, total_hits).

    Used by the training pipeline to walk through history one short window at a time, because a
    single search is capped at 10,000 hits.
    """
    params = {"q": query, "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
              "forms": forms, "from": offset}
    payload = json.loads(_get(SEARCH_URL + "?" + urllib.parse.urlencode(params), user_agent))
    total = payload.get("hits", {}).get("total", {}).get("value", 0)
    return _records(payload), total


def submissions(user_agent, cik):
    """Every filing a company has made, as a list of {form, date, items, adsh}, oldest first.

    The submissions API puts the newest ~1,000 filings in "recent" and lists older ones in extra
    files, which are fetched and merged here. Also returns the company's SIC industry code.
    """
    base = "https://data.sec.gov/submissions/"
    main = json.loads(_get(base + "CIK%010d.json" % int(cik), user_agent, max_bytes=8_000_000))
    blocks = [main.get("filings", {}).get("recent", {})]
    for extra in main.get("filings", {}).get("files", []):
        try:
            blocks.append(json.loads(_get(base + extra["name"], user_agent, max_bytes=8_000_000)))
        except EdgarError:
            pass
    rows = []
    for b in blocks:
        n = len(b.get("accessionNumber", []))
        for i in range(n):
            rows.append({"form": b["form"][i], "date": b["filingDate"][i], "adsh": b["accessionNumber"][i],
                         "items": [x for x in (b.get("items", [""] * n)[i] or "").split(",") if x],
                         "doc": b.get("primaryDocument", [""] * n)[i]})
    rows.sort(key=lambda r: r["date"])
    return {"name": main.get("name"), "sic": main.get("sic"), "tickers": main.get("tickers", []), "filings": rows}


_sic_cache = {}


def sic(user_agent, cik):
    """SIC industry code for a company (one small request, cached)."""
    if cik not in _sic_cache:
        try:
            main = json.loads(_get("https://data.sec.gov/submissions/CIK%010d.json" % int(cik), user_agent, max_bytes=8_000_000))
            _sic_cache[cik] = main.get("sic")
        except (EdgarError, ValueError):
            _sic_cache[cik] = None
    return _sic_cache[cik]
