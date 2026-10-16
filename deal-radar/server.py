"""Deal Radar server. Run with:  python3 server.py   then open http://127.0.0.1:8000

Standard library only. Reads settings from a .env file next to this script (see .env.example).
It binds to 127.0.0.1 so the API keys in .env stay on your machine.

Routes
  GET /                 the interface
  GET /api/status       which data sources are live
  GET /api/scan         scan EDGAR for new merger filings (cached 10 minutes; add ?refresh=1)
  GET /api/enrich?name= look up a company on Dealroom
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import edgar
import features
import llm
import market
import model as model_mod
import news
import pricing
import sample_data
import terms
from dealroom import Dealroom, DealroomError


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
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip() or None
DEALROOM = None
if os.environ.get("DEALROOM_CLIENT_ID") and os.environ.get("DEALROOM_CLIENT_SECRET"):
    DEALROOM = Dealroom(os.environ["DEALROOM_CLIENT_ID"], os.environ["DEALROOM_CLIENT_SECRET"],
                        os.environ.get("DEALROOM_BASE_URL", "https://api.dealroom.app"),
                        os.environ.get("DEALROOM_AUDIENCE", "https://api.dealroom.app"))

MODEL = model_mod.load()
_cache = {"at": 0.0, "payload": None}
_quotes = {}


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
    if ANTHROPIC_KEY and text:
        got = llm.extract(text, ANTHROPIC_KEY, LLM_MODEL)
        if got:
            extraction = "llm"
            for key in ("offer", "consideration", "expectedClose"):
                if got.get(key) is not None:
                    t[key] = got[key]
            if isinstance(got.get("flags"), dict):
                for k, v in got["flags"].items():
                    if v is not None:
                        t["flags"][k] = v
            t["parent"] = got.get("acquirer") or t["parent"]
            t["company"] = got.get("target") or t["company"]

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

    # Neither EDGAR nor Dealroom provides stock or option quotes, so the market and contract
    # fields start as clearly flagged placeholders for the user to replace with broker numbers.
    offer = t["offer"]
    spot = round(offer * 0.96, 2) if offer else None
    strike = round(spot) if spot else None
    market = {"spot": spot, "downside": round(spot / 1.28, 2) if spot else None, "assumed": True}
    contract = {"kind": "call", "strike": strike, "days": 90, "rate": 0.045, "vol": 0.40, "assumed": True,
                "premium": round(pricing.black_scholes(spot, strike, 90 / 365, 0.045, 0.20, "call"), 2) if spot else None}
    return {
        "id": rec["adsh"], "source": "edgar", "target": target, "ticker": rec["ticker"], "acquirer": acquirer,
        "filedOn": rec["filedOn"], "form": rec["form"], "items": rec["items"],
        "indexUrl": rec["indexUrl"], "docUrl": rec["docUrl"],
        "consideration": t["consideration"], "offer": offer, "expectedClose": t["expectedClose"],
        "closePhrase": t["closePhrase"], "flags": flags, "evidence": t["evidence"], "drivers": drivers,
        "pClose": p_close, "pPending": p_pending, "pSource": p_source, "timing": timing, "extraction": extraction,
        "market": market, "contract": contract, "dealroom": None,
        "note": "" if offer else "The agent could not find a price per share in this filing. Enter the offer price to continue.",
    }


def scan(days, limit):
    if not EDGAR_UA:
        return {"mode": "sample", "reason": "EDGAR_USER_AGENT is not set in .env", "deals": sample_data.sample_deals()}
    try:
        recs = edgar.search_filings(EDGAR_UA, days=days, query='"agreement and plan of merger"', forms="8-K")
        recs += edgar.search_filings(EDGAR_UA, days=days, query='"offer to purchase"', forms="SC TO-T")
        recs.sort(key=lambda r: r["filedOn"] or "", reverse=True)
        deals = []
        for rec in recs[:limit]:
            text = ""
            if rec["docUrl"]:
                try:
                    text = terms.to_text(edgar.fetch_document(EDGAR_UA, rec["docUrl"]))
                except edgar.EdgarError:
                    pass
            deals.append(build_deal(rec, text))
        return {"mode": "live", "deals": deals, "scannedAt": datetime.utcnow().isoformat() + "Z"}
    except (edgar.EdgarError, ValueError, KeyError) as e:
        return {"mode": "sample", "reason": str(e), "deals": sample_data.sample_deals()}


def page():
    with open(os.path.join(HERE, "static", "app.html"), encoding="utf-8") as f:
        body = f.read()
    body = body.replace("/*__SAMPLE__*/[]", json.dumps(sample_data.sample_deals()))
    body = body.replace("/*__NEWSCFG__*/{}", json.dumps(news.config()))
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
            return self._send(200, {"edgar": bool(EDGAR_UA), "dealroom": DEALROOM is not None, "llm": bool(ANTHROPIC_KEY),
                                    "model": model_status(), "yfinance": yf})
        if url.path == "/api/news":
            ticker = (q.get("ticker") or [""])[0].strip().upper()
            names = [x for x in (q.get("name", [""])[0], q.get("acquirer", [""])[0]) if x]
            if not ticker:
                return self._send(200, {"error": "This deal has no ticker, so there is no news feed to read."})
            try:
                return self._send(200, news.for_ticker(ticker, names))
            except news.NewsError as e:
                return self._send(200, {"error": str(e)})
        if url.path == "/api/quote":
            ticker = (q.get("ticker") or [""])[0].strip().upper()
            if not ticker or len(ticker) > 12:
                return self._send(200, {"error": "Enter a ticker."})
            kind = (q.get("kind") or [""])[0]
            try:
                strike = float(q["strike"][0]) if q.get("strike") and q["strike"][0] else None
                days = int(float(q.get("days", ["60"])[0] or 60))
            except ValueError:
                strike, days = None, 60
            key = (ticker, kind, strike, days)
            hit = _quotes.get(key)
            if hit and time.time() - hit[0] < 120:
                return self._send(200, hit[1])
            try:
                res = market.quote(ticker, kind, strike, days)
            except market.MarketError as e:
                res = {"ticker": ticker, "error": str(e)}
            _quotes[key] = (time.time(), res)
            return self._send(200, res)
        if url.path == "/api/history":
            tickers = [x.strip().upper() for x in (q.get("tickers") or [""])[0].split(",") if x.strip()][:40]
            if not tickers:
                return self._send(200, {"error": "No tickers given."})
            try:
                return self._send(200, market.history_many(tickers, int((q.get("days") or ["504"])[0])))
            except (market.MarketError, ValueError) as e:
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
            fresh = time.time() - _cache["at"] < 600 and _cache["payload"] and not q.get("refresh")
            if not fresh:
                days = int(q.get("days", ["30"])[0])
                _cache["payload"], _cache["at"] = scan(max(1, min(days, 120)), 12), time.time()
            return self._send(200, _cache["payload"])
        if url.path == "/api/enrich":
            name = (q.get("name") or [""])[0].strip()
            if not DEALROOM:
                return self._send(200, {"configured": False, "company": None})
            try:
                return self._send(200, {"configured": True, "company": DEALROOM.find_company(name) if name else None})
            except (DealroomError, Exception) as e:  # keep the interface working if Dealroom errors
                return self._send(200, {"configured": True, "company": None, "error": str(e)})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("Deal Radar on http://127.0.0.1:%d  | EDGAR %s | Dealroom %s | LLM %s | close odds from %s" % (
        port, "ready" if EDGAR_UA else "needs EDGAR_USER_AGENT (using sample data)",
        "ready" if DEALROOM else "not configured", "on" if ANTHROPIC_KEY else "off (rules only)",
        "trained model on %d deals" % MODEL["n_deals"] if MODEL else "hand-written rules (no data/model.json yet)"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
