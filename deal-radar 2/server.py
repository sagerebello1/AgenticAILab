"""Deal Radar server. Run with:  python3 server.py   then open http://127.0.0.1:8000

Standard library only. Reads EDGAR_USER_AGENT from a .env file next to this script.
It binds to 127.0.0.1. No paid API is called, even if a key for one is present in the environment.

Routes
  GET  /                 the interface
  GET  /api/status       which free data sources are live
  GET  /api/scan         scan EDGAR for new merger filings (cached 10 minutes; add ?refresh=1)
  GET  /api/quote        one bid/ask from offer, spot, downside, days
  POST /api/quote        same fields as JSON
  GET  /api/quote/live   same, and fill a missing price from Yahoo's public chart.
                         news=1 adds Yahoo's public headline feed.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import edgar
import features
import market
import model as model_mod
import news
import options
import quote
import terms
import workflow


def load_env(path):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


load_env(os.path.join(HERE, ".env"))

EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "").strip()

MODEL = model_mod.load()
SCAN_SECONDS = workflow.seconds("DEAL_RADAR_SCAN_SECONDS", 1800, 120)
PRICE_SECONDS = workflow.seconds("DEAL_RADAR_PRICE_SECONDS", 300, 60)
WORK = workflow.Workflow(scan_fn=lambda: scan(30, 12), scan_seconds=SCAN_SECONDS, price_seconds=PRICE_SECONDS)


def model_status():
    if not MODEL:
        return None
    t = MODEL["test"]
    return {"n": MODEL["n_deals"], "from": MODEL["date_range"][0], "to": MODEL["date_range"][1],
            "brier": t["logistic regression"]["brier"], "baseBrier": t["base rate"]["brier"], "rulesBrier": t["hand-written rules"]["brier"]}


def build_deal(rec, text):
    """Combine the filing record, extracted terms and the odds into one deal."""
    t = terms.extract_terms(text) if text else {"offer": None, "consideration": None, "expectedClose": None,
                                                 "closePhrase": None, "parent": None, "company": None,
                                                 "evidence": {}, "flags": {}}
    extraction = "rules"

    filer = rec["filer"] or "Unknown filer"
    target, acquirer = filer, t["parent"] or "See filing"
    # If the filer looks like the buyer, the target is the other named party.
    if t["parent"] and filer.lower().split()[0] == t["parent"].lower().split()[0] and t["company"]:
        target, acquirer = t["company"], filer

    flags = t["flags"]
    p_close, p_pending, drivers = terms.estimate_probabilities(t["consideration"], flags)
    p_source, timing = "rules", None
    if MODEL and text:
        row, _ = features.vectorize(text, edgar.sic(EDGAR_UA, rec["cik"]))
        p_close, drivers = model_mod.predict(MODEL, row)
        p_close = round(min(0.99, max(0.02, p_close)), 3)
        p_pending = round(min(0.97, max(0.2, p_close - 0.06)), 3)
        p_source = "model"
        if rec["filedOn"]:
            elapsed = max(0, (date.today() - date.fromisoformat(rec["filedOn"])).days)
            timing = {"curve": model_mod.timing_curve(MODEL, row), "elapsed": elapsed}

    # Prices come from the filing and from Yahoo. Nothing here is invented.
    offer = t["offer"]
    spot = None
    prices = {"spot": None, "downside": None, "assumed": True}
    contract = {"kind": "call", "strike": None, "days": 90, "rate": 0.045, "vol": 0.40, "assumed": True, "premium": None}
    market_error = None
    if rec.get("ticker") and rec.get("filedOn"):
        try:
            filed = date.fromisoformat(rec["filedOn"])
            series = market.history(rec["ticker"], filed - timedelta(days=160), date.today() + timedelta(days=1))
            stats = market.stats(series, filed)
            if stats.get("spot"):
                prices["spot"] = round(stats["spot"], 2)
                spot = prices["spot"]
            if stats.get("downside"):
                prices["downside"] = round(stats["downside"], 2)
                prices["assumed"] = False
            if stats.get("vol") and stats["vol"] > 0:
                contract["vol"] = round(min(stats["vol"], 1.5), 2)
            if stats.get("asOf"):
                prices["asOf"] = stats["asOf"]
            prices["source"] = "yahoo-chart"
        except (market.MarketError, ValueError) as e:
            market_error = "Yahoo did not return a price for %s. %s" % (rec.get("ticker"), e)
    # A "$1.00 per share" buried in a filing is not an offer when the stock trades at $40.
    if offer and prices.get("spot") and not (0.4 * prices["spot"] <= offer <= 3 * prices["spot"]):
        filing_status = "terms_need_verification"
        note = "The filing mentions $%s per share, which is far from the $%s stock price, so it was not used as the offer." % (offer, prices["spot"])
        offer = None
    else:
        filing_status, note = terms.filing_status(text, offer, rec.get("docError"), bool(rec.get("docUrl") or rec.get("sources")))
    return {
        "id": rec["adsh"], "cik": rec.get("cik"), "source": "edgar", "target": target, "ticker": rec["ticker"], "acquirer": acquirer,
        "filedOn": rec["filedOn"], "form": rec["form"], "items": rec["items"],
        "indexUrl": rec["indexUrl"], "docUrl": rec["docUrl"],
        "consideration": t["consideration"], "offer": offer, "expectedClose": t["expectedClose"],
        "closePhrase": t["closePhrase"], "flags": flags, "evidence": t["evidence"], "drivers": drivers,
        "pClose": p_close, "pPending": p_pending, "pSource": p_source, "timing": timing, "extraction": extraction,
        "market": prices, "marketError": market_error, "contract": contract,
        "filingStatus": filing_status, "note": note, "sources": rec.get("sources") or [],
        "catalyst": options.catalyst(note, flags, filing_status),
    }


def read_filing(rec):
    """Read the matched document, then a press release or the form if the price is not there."""
    chunks, sources, error = [], [], None
    primary = rec.get("docUrl")
    if primary:
        try:
            chunks.append(terms.to_text(edgar.fetch_document(EDGAR_UA, primary)))
            label = edgar._doc_name(primary) or rec.get("form") or "Filing"
            sources.append({"label": label, "url": primary, "type": rec.get("form") or ""})
        except edgar.EdgarError as e:
            error = str(e)
    if terms.best_offer("\n".join(chunks))[0] is None and rec.get("indexUrl"):
        try:
            listed = edgar.list_documents(EDGAR_UA, rec["indexUrl"])
        except edgar.EdgarError as e:
            error = error or str(e)
            listed = []
        for doc in edgar.supporting_documents(listed, skip_url=primary)[:3]:
            try:
                chunks.append(terms.to_text(edgar.fetch_document(EDGAR_UA, doc["url"])))
            except edgar.EdgarError as e:
                error = error or str(e)
                continue
            label = doc["type"] + ((" — " + doc["description"]) if doc.get("description") else "")
            sources.append({"label": label, "url": doc["url"], "type": doc["type"]})
            if terms.best_offer(chunks[-1])[0] is not None:
                break
    if rec.get("indexUrl"):
        sources.append({"label": "Filing index", "url": rec["indexUrl"], "type": "index"})
    return "\n".join(chunks), sources, error


def scan(days, limit):
    if not EDGAR_UA:
        return {"mode": "error", "reason": "EDGAR_USER_AGENT is not set. Add your name and email to the .env file next to server.py. The SEC requires that contact and does not require a key.", "deals": []}
    try:
        recs = edgar.search_filings(EDGAR_UA, days=days, query='"agreement and plan of merger"', forms="8-K")
        recs += edgar.search_filings(EDGAR_UA, days=days, query='"offer to purchase"', forms="SC TO-T")
        recs.sort(key=lambda r: r["filedOn"] or "", reverse=True)
        announced = [r for r in recs if r.get("ticker") and (
            "1.01" in (r.get("items") or []) or (r.get("form") or "").startswith("SC TO"))]
        chosen, seen = [], set()
        for rec in (announced or recs):
            key = (rec.get("ticker") or rec.get("adsh") or "").upper()
            if key in seen:
                continue
            seen.add(key)
            chosen.append(rec)
            if len(chosen) >= limit:
                break
        deals = []
        for rec in chosen:
            text, sources, doc_error = read_filing(rec)
            rec = dict(rec, sources=sources, docError=doc_error)
            deals.append(build_deal(rec, text))
        return {"mode": "live", "deals": deals, "scannedAt": datetime.utcnow().isoformat() + "Z"}
    except (edgar.EdgarError, ValueError, KeyError) as e:
        return {"mode": "error", "reason": "SEC EDGAR did not answer. %s" % e, "deals": []}


def page():
    with open(os.path.join(HERE, "static", "app.html"), encoding="utf-8") as f:
        body = f.read()
    body = body.replace("/*__SAMPLE__*/[]", "[]")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body>" + body + "</body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, payload, ctype="application/json"):
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            return self._send(200, page(), "text/html")
        if url.path == "/api/status":
            try:
                import yfinance  # noqa: F401
                yf = True
            except ImportError:
                yf = False
            return self._send(200, {"edgar": bool(EDGAR_UA), "dealroom": False, "llm": False,
                                    "model": model_status(), "yfinance": yf,
                                    "quote": True,
                                    "quoteSources": ["filing-rules", "yahoo-chart", "yahoo-rss"],
                                    "paid": [],
                                    "options": options.CHAIN,
                                    "optionsAudit": options.AUDIT,
                                    "workflow": WORK.status()})
        if url.path == "/api/news":
            ticker = (q.get("ticker") or [""])[0].strip().upper()
            names = [x for x in (q.get("name", [""])[0], q.get("acquirer", [""])[0]) if x]
            if not ticker:
                return self._send(200, {"error": "This deal has no ticker, so there is no news feed to read."})
            try:
                return self._send(200, news.for_ticker(ticker, names))
            except news.NewsError as e:
                return self._send(200, {"error": str(e)})
        if url.path == "/api/market":
            ticker = (q.get("ticker") or [""])[0].strip().upper()
            try:
                filed = date.fromisoformat(q["filedOn"][0]) if q.get("filedOn") and q["filedOn"][0] else None
                strike = float(q["strike"][0]) if q.get("strike") and q["strike"][0] else None
                days = int(float(q.get("days", ["60"])[0]))
                return self._send(200, market.snapshot(ticker, filed, (q.get("kind") or ["call"])[0], strike, days))
            except (market.MarketError, ValueError) as e:
                return self._send(200, {"error": str(e)})
        if url.path == "/api/scan":
            return self._scan(q)
        if url.path == "/api/quotes":
            return self._send(400, {"error": "Fictional sample companies are not served. Use a filing from the scan."})
        if url.path == "/api/quote":
            return self._quote(q, live=False)
        if url.path == "/api/quote/live":
            return self._quote(q, live=True)
        if url.path == "/api/options/status":
            return self._send(200, options.CHAIN)
        if url.path == "/api/enrich":
            return self._send(200, {"configured": False, "company": None,
                                    "error": "Dealroom is a paid data service and is not called."})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/options":
            return self._options_research(self._json_body())
        if url.path not in ("/api/quote", "/api/quote/live"):
            return self._send(404, {"error": "not found"})
        body = self._json_body()
        if body is None:
            return
        self._quote(body, live=url.path.endswith("/live"))

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "Content-Length must be an integer."})
            return None
        if n > 100_000:
            self._send(400, {"error": "Body is limited to 100KB."})
            return None
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "Body must be JSON."})
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "Body must be a JSON object."})
            return None
        return body

    def _options_research(self, body):
        if body is None:
            return
        for side in ("call", "put"):
            leg = body.get(side)
            if isinstance(leg, dict):
                leg["source"] = "manual"
                leg.pop("quotedAt", None)
        self._send(200, options.analyze(body))

    def _scan(self, q):
        force = bool(q.get("refresh"))
        due = WORK._scan_mono == 0 or time.monotonic() - WORK._scan_mono >= WORK.scan_seconds
        if force or due:
            if WORK._scan_lock.acquire(blocking=not WORK.book):
                try:
                    still_due = force or WORK._scan_mono == 0 or time.monotonic() - WORK._scan_mono >= WORK.scan_seconds
                    if still_due:
                        days = int(q.get("days", ["30"])[0])
                        WORK.ingest(scan(max(1, min(days, 120)), 12))
                finally:
                    WORK._scan_lock.release()
        return self._send(200, WORK.payload())

    def _quote(self, params, live):
        if params.get("id"):
            return self._send(400, {"error": "Pass offer, spot, downside and days from a real filing. Sample company ids are not served."})
        try:
            return self._send(200, quote.respond(params, live=live))
        except quote.InputError as e:
            return self._send(400, {"error": str(e)})
        except quote.UpstreamError as e:
            return self._send(200, {"error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("Deal Radar on http://127.0.0.1:%d  | EDGAR %s | close odds from %s | scan every %ds | prices every %ds | paid APIs off" % (
        port, "ready" if EDGAR_UA else "needs EDGAR_USER_AGENT",
        "trained model on %d deals" % MODEL["n_deals"] if MODEL else "hand-written rules",
        SCAN_SECONDS, PRICE_SECONDS))
    WORK.start()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
