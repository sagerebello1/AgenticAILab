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
import os
import re
import ssl
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


def _ssl_context():
    """Use the system certificate bundle when this Python has none of its own."""
    ca = "/etc/ssl/cert.pem"
    if os.path.exists(ca):
        try:
            return ssl.create_default_context(cafile=ca)
        except ssl.SSLError:
            pass
    return ssl.create_default_context()


def _get(url, user_agent, max_bytes=1_500_000, timeout=20):
    wait = 0.12 - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
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


_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _cell_text(cell):
    text = _TAG_RE.sub(" ", cell)
    text = html_unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def html_unescape(value):
    return (value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))


def parse_index(page, page_url):
    """Documents listed on an EDGAR filing index page.

    Each item is {type, description, url, name}. Graphics, XBRL, and the complete
    submission file are left out. The type and URL come from the index table.
    """
    if isinstance(page, bytes):
        page = page.decode("utf-8", errors="replace")
    block = page
    marked = re.search(r'summary="Document Format Files"(.*?)</table>', page, re.I | re.S)
    if marked:
        block = marked.group(1)
    docs = []
    for row in _ROW_RE.findall(block):
        cells = _CELL_RE.findall(row)
        if len(cells) < 4:
            continue
        href = _HREF_RE.search(cells[2])
        kind = _cell_text(cells[3])
        if not href or not kind:
            continue
        url = urllib.parse.urljoin(page_url, html_unescape(href.group(1)))
        docs.append({
            "type": kind,
            "description": _cell_text(cells[1]),
            "url": url,
            "name": urllib.parse.urlparse(url).path.rsplit("/", 1)[-1],
        })
    return docs


def _doc_name(url):
    """File name, including when the index links through the SEC viewer (/ix?doc=)."""
    parsed = urllib.parse.urlparse(url or "")
    target = urllib.parse.parse_qs(parsed.query).get("doc", [parsed.path])[0]
    return target.rstrip("/").rsplit("/", 1)[-1].lower()


def supporting_documents(docs, skip_url=""):
    """Press releases and the form itself, ahead of the long merger agreement."""
    skip = _doc_name(skip_url)

    def rank(doc):
        kind = (doc.get("type") or "").upper()
        desc = (doc.get("description") or "").upper()
        if kind.startswith("EX-99") or "PRESS" in desc:
            return 0
        if kind.startswith("8-K") or kind.startswith("SC TO") or kind.startswith("SC 14D"):
            return 1
        if kind.startswith("EX-2"):
            return 2
        return 9

    chosen = []
    seen = set()
    for doc in sorted(docs, key=rank):
        if rank(doc) >= 9:
            continue
        name = _doc_name(doc.get("url") or doc.get("name") or "")
        if not name or name in seen or name == skip:
            continue
        seen.add(name)
        chosen.append(doc)
    return chosen


def list_documents(user_agent, index_url):
    """Download a filing index and return its document rows."""
    return parse_index(fetch_document(user_agent, index_url, max_bytes=400_000), index_url)


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
