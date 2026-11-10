"""Discover listed filers from recent SEC activity, independently of deal quote eligibility."""
import json
import time
import re
import edgar
import filing_brief

from datetime import date, datetime, timedelta, timezone
import threading
import urllib.parse

_profiles = {}
_lock = threading.Lock()
_feed = None
_checked = 0.0
TTL = 300

def industry(code):
    try:
        n = int(code)
    except (ValueError, TypeError):
        return "Unclassified"
    if 8000 <= n <= 8099 or 2830 <= n <= 2839 or 3840 <= n <= 3851: return "Healthcare"
    if 7370 <= n <= 7379 or 3570 <= n <= 3579 or 3670 <= n <= 3679: return "Technology"
    if 1300 <= n <= 1399 or 2900 <= n <= 2999: return "Energy"
    if 6000 <= n <= 6799: return "Finance & real estate"
    if 5000 <= n <= 5999: return "Wholesale & retail"
    if 2000 <= n <= 3999: return "Manufacturing"
    if 4000 <= n <= 4999: return "Transportation & utilities"
    if 1500 <= n <= 1799: return "Construction"
    if 7000 <= n <= 8999: return "Services"
    return "Other"

def _hits(ua, days, forms, query=None):
    end=date.today()
    args=dict(startdt=(end-timedelta(days=days)).isoformat(),enddt=end.isoformat(),
              dateRange="custom", forms=forms, size=100)
    if query: args["q"]=query
    payload=json.loads(edgar._get(edgar.SEARCH_URL+"?"+urllib.parse.urlencode(args), ua))
    return [h["_source"] for h in payload["hits"]["hits"]]

def _collect(ua):
    mapping=edgar.company_ticker_map(ua)
    issuers={}
    for x in sorted(mapping.values(), key=lambda x:(len(x["ticker"]),x["ticker"])):
        issuers.setdefault(int(x["cik"]),x)
    rows={}
    for days,forms,q,ma in [(7,"10-K,10-Q,8-K",None,False),(30,"8-K",'"agreement and plan of merger"',True),(30,"SC TO-T",None,True)]:
        for hit in _hits(ua,days,forms,q):
            ciks=hit.get("ciks") or []
            if len(ciks)!=1: continue  # Do not guess which joint filer the signal belongs to.
            cik=int(ciks[0])
            entity=issuers.get(cik)
            accession=hit.get("adsh","")
            if not entity or not re.fullmatch(r"\d{10}-\d{2}-\d{6}",accession): continue
            r=rows.setdefault(cik,dict(entity,industry=industry((hit.get("sics") or [None])[0]),latest=None,merger=None))
            f=dict(date=hit["file_date"],form=hit["form"],url="https://www.sec.gov/Archives/edgar/data/%d/%s/%s-index.htm"%(cik,accession.replace("-",""),accession),accession=accession)
            for k in (("latest","merger") if ma else ("latest",)):
                if not r[k] or (f["date"],accession)>(r[k]["date"],r[k]["accession"]):r[k]=f
    return dict(companies=sorted(rows.values(),key=lambda r:r["latest"]["date"],reverse=True),
                updatedAt=datetime.now(timezone.utc).isoformat(), stale=False)

def directory(ua):
    global _feed,_checked
    if not ua: raise ValueError("SEC contact missing")
    with _lock:
        if _feed is not None and time.monotonic()-_checked<TTL: return _feed
        try:
            result=_collect(ua)
        except (edgar.EdgarError, OSError, ValueError, KeyError):
            if _feed is None: raise ValueError("SEC feed unavailable")
            result=dict(_feed,stale=True)
        _feed,_checked=result,time.monotonic()
        return result

def profile(ua, ticker):
    row=edgar.find_company(ua,ticker)
    if not row: raise KeyError(ticker)
    cik = int(row["cik"])
    if cik in _profiles and time.monotonic() - _profiles[cik][0] < 900:
        return _profiles[cik][1]
    data = json.loads(edgar._get("https://data.sec.gov/submissions/CIK%010d.json" % cik, ua, max_bytes=12000000))
    recent = data.get("filings", {}).get("recent", {})
    filings = []
    for i,(form, date, accession) in enumerate(zip(recent.get("form", []), recent.get("filingDate", []), recent.get("accessionNumber", []))):
        if (filings and form not in ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A")) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            continue
        url = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s-index.htm" % (cik, accession.replace("-", ""), accession)
        doc=(recent.get("primaryDocument") or [""])[i]
        direct=(url.rsplit("/",1)[0]+"/"+doc) if re.fullmatch(r"[A-Za-z0-9_./-]+",doc or "") and ".." not in doc and not doc.startswith("/") else None
        filing=dict(form=form,date=date,url=url,document=direct,label=filing_brief.describe(form),period=recent["reportDate"][i],items=recent["items"][i])
        if not filings and direct:
            try:
                limit=10_000_000
                raw=edgar._get(direct,ua,max_bytes=limit)
                if len(raw)<limit:
                    filing["brief"]=filing_brief.summarize(raw,filing,cik,row["name"])
            except (edgar.EdgarError,OSError,ValueError,ArithmeticError):
                pass
        filings.append(filing)
        if len(filings) == 3:
            break
    result = dict(row, industry=industry(data.get("sic")), classification=data.get("sicDescription"), exchanges=data.get("exchanges", []), filings=filings)
    _profiles[cik] = (time.monotonic(), result)
    return result
