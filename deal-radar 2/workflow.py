"""Scheduled filing book. Merges EDGAR scans, refreshes delayed stock prices, and
recalculates the existing quote when the inputs change.

No options chain is called. A daily Yahoo bar is never labeled real-time.
"""
import copy
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import market
import quote


def seconds(name, default, minimum):
    """Positive interval from the environment, never below `minimum`."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return max(minimum, value)


def deal_key(deal):
    ticker = (deal.get("ticker") or "").strip().upper()
    if ticker:
        return "T:" + ticker
    return "A:" + str(deal.get("id") or "")


def _iso(when):
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(when)


def price_label(as_of, today=None):
    """delayed, stale, or unavailable. Never real-time.

    A daily bar from today or the last four calendar days is delayed.
    Older than that is stale. A missing bar date is unavailable.
    """
    if not as_of:
        return "unavailable"
    try:
        bar = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return "unavailable"
    day = today or date.today()
    age = (day - bar).days
    if age < 0:
        return "unavailable"
    if age > 4:
        return "stale"
    return "delayed"


def stamp_price(deal, retrieved_at, today=None):
    """Record where the stock price came from. Does not invent a price."""
    deal = copy.deepcopy(deal)
    prices = deal.get("market") or {}
    spot = prices.get("spot")
    as_of = prices.get("asOf")
    label = price_label(as_of, today) if spot else "unavailable"
    note = "Yahoo's daily chart is unofficial. It is delayed, not a real-time quote."
    if not spot:
        note = deal.get("marketError") or "No stock price was returned."
        label = "unavailable"
    elif label == "stale":
        note = "The latest Yahoo daily bar is more than four days old. It is stale, not a real-time quote."
    elif not as_of:
        label = "unavailable"
        note = "A price came back without a bar date, so it is not labeled real-time."
    deal["price"] = {
        "source": "yahoo-chart" if spot else None,
        "retrievedAt": _iso(retrieved_at),
        "asOf": as_of,
        "freshness": label,
        "note": note,
    }
    return deal


def _close_days(deal, today=None):
    today = today or date.today()
    raw = deal.get("expectedClose")
    if raw:
        try:
            remaining = (date.fromisoformat(str(raw)[:10]) - today).days
        except ValueError:
            remaining = None
        if remaining and remaining > 0:
            return remaining
    return 120


def _quote_params(deal, days):
    prices = deal.get("market") or {}
    params = {
        "offer": deal.get("offer"),
        "spot": prices.get("spot"),
        "downside": prices.get("downside"),
        "days": days,
        "ticker": deal.get("ticker"),
    }
    if deal.get("consideration"):
        params["consideration"] = deal["consideration"]
    flags = deal.get("flags") or {}
    for name in ("hsr", "secondRequest", "foreign", "other", "financingCondition", "tender", "vote", "goShop"):
        if name in flags and flags[name] is not None:
            params[name] = flags[name]
    return params


def recalculate(deal, today=None):
    """Rerun the existing stock quote when offer, spot, downside, and days are present.

    The close chance stays the rules-based filing estimate. It is not refit.
    """
    days = _close_days(deal, today)
    prices = deal.get("market") or {}
    inputs = [deal.get("offer"), prices.get("spot"), prices.get("downside"), days]
    previous = deal.get("metrics") or {}
    if previous.get("inputs") == inputs and "quote" in previous:
        return deal
    if not all(isinstance(v, (int, float)) and v > 0 for v in inputs):
        deal["metrics"] = {"quote": None, "inputs": inputs, "reason": "The quote needs a cash offer, a stock price, and a break price."}
        return deal
    try:
        result = quote.respond(_quote_params(deal, days))
    except quote.InputError as e:
        deal["metrics"] = {"quote": None, "inputs": inputs, "reason": str(e)}
        return deal
    deal["metrics"] = {
        "quote": {key: result[key] for key in ("fairValue", "bid", "ask", "action", "pMarket", "discountedOffer", "charge", "pClose")},
        "inputs": inputs,
        "calculatedAt": _iso(datetime.now(timezone.utc)),
        "note": "Recalculated from the filing rules and the current prices. The close chance is still a rules-based estimate.",
    }
    return deal


def _filing_changed(previous, deal):
    for field in ("id", "filedOn", "filingStatus", "offer", "note"):
        if (previous.get(field) or None) != (deal.get(field) or None):
            return True
    return False


def merge_deals(book, incoming):
    """One row per ticker. A newer filing replaces the old one. An older one does not."""
    by_key, order = {}, []
    for deal in book:
        key = deal_key(deal)
        if key not in by_key:
            order.append(key)
            by_key[key] = deal
    added, updated = [], []
    for raw in incoming:
        deal = copy.deepcopy(raw)
        key = deal_key(deal)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = deal
            order.append(key)
            added.append(key)
            continue
        same = deal.get("id") and deal.get("id") == previous.get("id")
        new_date = deal.get("filedOn") or ""
        prev_date = previous.get("filedOn") or ""
        if not same and new_date < prev_date:
            continue
        changed = _filing_changed(previous, deal)
        if changed:
            deal["statusChanged"] = True
            deal["previousFiling"] = {
                "id": previous.get("id"), "filedOn": previous.get("filedOn"),
                "filingStatus": previous.get("filingStatus"), "offer": previous.get("offer"),
            }
            by_key[key] = deal
            updated.append(key)
        elif (deal.get("market") or {}).get("spot"):
            kept = copy.deepcopy(previous)
            kept["market"] = deal.get("market")
            kept["marketError"] = deal.get("marketError")
            kept["price"] = deal.get("price") or kept.get("price")
            by_key[key] = kept
    return [by_key[key] for key in order], {"added": added, "updated": updated}


def active_quoted(deal):
    """A filing sentence quoted a cash price and the event is not a termination or a close."""
    if deal.get("filingStatus") != "extracted" or not deal.get("offer"):
        return False
    kind = ((deal.get("catalyst") or {}).get("kind")) or ""
    return kind not in ("termination", "completed")


def yahoo_spot(ticker):
    """Latest daily close only. The pre-announcement price is left as it was."""
    series = market.history(ticker, date.today() - timedelta(days=14), date.today() + timedelta(days=1))
    if not series:
        raise market.MarketError("Yahoo returned no prices for %s" % ticker)
    return {"spot": series[-1][1], "asOf": series[-1][0].isoformat()}


def apply_spot(deal, stats, retrieved_at, today=None):
    prices = dict(deal.get("market") or {})
    if stats.get("spot"):
        prices["spot"] = round(float(stats["spot"]), 2)
    if stats.get("asOf"):
        prices["asOf"] = stats["asOf"]
    prices["source"] = "yahoo-chart"
    deal["market"] = prices
    labeled = stamp_price(deal, retrieved_at, today)
    deal["price"] = labeled["price"]
    return deal


class Workflow:
    """In-memory book. The background loop starts only when start() is called."""

    def __init__(self, scan_fn=None, price_fn=None, scan_seconds=1800, price_seconds=300):
        self.scan_fn = scan_fn or (lambda: {"mode": "error", "reason": "No scan function.", "deals": []})
        self.price_fn = price_fn or yahoo_spot
        self.scan_seconds = scan_seconds
        self.price_seconds = price_seconds
        self.book = []
        self.last_scan_ok = None
        self.last_scan_error = None
        self.last_price_ok = None
        self.last_price_error = None
        self._scan_mono = 0.0
        self._price_mono = 0.0
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def ingest(self, payload, retrieved_at=None):
        now = retrieved_at or datetime.now(timezone.utc)
        if payload.get("mode") != "live":
            self.last_scan_error = payload.get("reason") or "SEC EDGAR did not answer."
            self._scan_mono = time.monotonic()
            return {"added": [], "updated": []}
        stamped = []
        for deal in payload.get("deals") or []:
            row = stamp_price(deal, now)
            recalculate(row)
            stamped.append(row)
        with self._lock:
            self.book, changes = merge_deals(self.book, stamped)
            for deal in self.book:
                recalculate(deal)
        self.last_scan_ok = payload.get("scannedAt") or _iso(now)
        self.last_scan_error = None
        self._scan_mono = time.monotonic()
        if any((deal.get("market") or {}).get("spot") for deal in stamped):
            self.last_price_ok = _iso(now)
            self.last_price_error = None
            self._price_mono = time.monotonic()
        return changes

    def refresh_prices(self, now=None, today=None):
        now = now or datetime.now(timezone.utc)
        with self._lock:
            rows = list(self.book)
        errors, ok = [], False
        for deal in rows:
            ticker = deal.get("ticker")
            if not ticker:
                continue
            try:
                stats = self.price_fn(ticker)
            except Exception as e:
                errors.append("%s: %s" % (ticker, e))
                continue
            with self._lock:
                current = next((row for row in self.book if deal_key(row) == deal_key(deal)), None)
                if current is None:
                    continue
                apply_spot(current, stats, now, today)
                recalculate(current)
            ok = True
        if ok:
            self.last_price_ok = _iso(now)
            self._price_mono = time.monotonic()
        self.last_price_error = "; ".join(errors) if errors else None
        return {"ok": ok, "errors": errors}

    def payload(self):
        with self._lock:
            deals = copy.deepcopy(self.book)
        if not deals and self.last_scan_error:
            return {"mode": "error", "reason": self.last_scan_error, "deals": [], "scannedAt": self.last_scan_ok}
        return {"mode": "live", "deals": deals, "scannedAt": self.last_scan_ok}

    def status(self):
        with self._lock:
            quoted = sum(1 for deal in self.book if active_quoted(deal))
            tracked = len(self.book)
        return {
            "lastScan": self.last_scan_ok,
            "lastScanError": self.last_scan_error,
            "lastPriceRefresh": self.last_price_ok,
            "lastPriceError": self.last_price_error,
            "scanSeconds": self.scan_seconds,
            "priceSeconds": self.price_seconds,
            "activeQuoted": quoted,
            "tracked": tracked,
            "optionsAvailable": False,
            "activeQuotedNote": "A filing sentence stated a cash price per share, and the filing was not read as a termination or a completed deal. That is not an independent confirmation.",
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="DealRadarRefresh", daemon=True)
        self._thread.start()

    def _run_scan(self):
        if not self._scan_lock.acquire(blocking=False):
            return
        try:
            self.ingest(self.scan_fn())
        except Exception as e:
            self.last_scan_error = str(e)
            self._scan_mono = time.monotonic()
        finally:
            self._scan_lock.release()

    def _loop(self):
        if self._stop.wait(20):
            return
        while not self._stop.is_set():
            due = self._scan_mono == 0 or time.monotonic() - self._scan_mono >= self.scan_seconds
            if due:
                self._run_scan()
            if self.book and (self._price_mono == 0 or time.monotonic() - self._price_mono >= self.price_seconds):
                try:
                    self.refresh_prices()
                except Exception as e:
                    self.last_price_error = str(e)
            if self._stop.wait(15):
                return
