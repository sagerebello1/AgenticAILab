"""Live price feed for Deal Radar.

Two sources, used in this order:

  1. Finnhub (needs a free API key in .env as FINNHUB_API_KEY, from finnhub.io).
       * WebSocket: every trade is pushed the moment it happens.
       * REST /quote: polled in the background. It supplies yesterday's close (for the day change)
         and keeps prices flowing if the WebSocket drops or the symbol has no trades.
  2. Yahoo Finance chart endpoint (no key): polled, usually delayed about 15 minutes, unofficial,
     and rate-limited without notice. Used only when there is no Finnhub key.

The browser connects once to /api/live/stream (Server-Sent Events) and receives price changes as
they arrive. The server keeps one connection to the data provider no matter how many pages are open.

Free-tier limits change. At the time of writing Finnhub's free plan allowed about 60 REST calls a
minute and 50 WebSocket symbols, but check finnhub.io/pricing for your plan. The poller keeps itself
under REQUESTS_PER_MINUTE and backs off for 30 seconds if the provider answers HTTP 429.

The WebSocket client below is a small, dependency-free implementation of RFC 6455 (text frames,
ping/pong, close). It is only as tested as the notes in README.md say.
"""
import base64
import hashlib
import json
import os
import queue
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:      # no tz database on this machine
    NY = None

UA = "Mozilla/5.0 (compatible; DealRadar research prototype)"
FINNHUB_REST = "https://finnhub.io/api/v1"
FINNHUB_WS = "wss://ws.finnhub.io"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1m&range=1d"
REQUESTS_PER_MINUTE = 45      # stay under a 60/minute limit with room for news and quote lookups
MAX_SYMBOLS = 50


def market_open(now=None):
    """True during regular US trading hours (9:30 to 16:00 New York time, weekdays). Holidays are not known."""
    if NY is None:
        return True
    t = (now or datetime.now(NY)).astimezone(NY)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


# ---------------------------------------------------------------------------------------------
# Minimal WebSocket client
# ---------------------------------------------------------------------------------------------
class WSClosed(Exception):
    pass


class WSClient:
    def __init__(self, url, timeout=15):
        self.url, self.timeout = url, timeout
        self.sock = None
        self.rfile = None
        self._send_lock = threading.Lock()

    def connect(self):
        u = urllib.parse.urlsplit(self.url)
        secure = u.scheme == "wss"
        host, port = u.hostname, u.port or (443 if secure else 80)
        raw = socket.create_connection((host, port), timeout=self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if secure else raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nUser-Agent: %s\r\n\r\n") % (path, u.netloc, key, UA)
        self.sock.sendall(req.encode())
        self.rfile = self.sock.makefile("rb")
        status = self.rfile.readline().decode("latin-1").strip()
        headers = {}
        while True:
            line = self.rfile.readline().decode("latin-1")
            if line in ("\r\n", "\n", ""):
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        if " 101 " not in status + " ":
            raise WSClosed("Server refused the WebSocket: %s" % status)
        want = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != want:
            raise WSClosed("WebSocket handshake check failed")

    def _frame(self, opcode, payload=b""):
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    def send_text(self, text):
        with self._send_lock:
            self.sock.sendall(self._frame(0x1, text.encode()))

    def send_ping(self):
        with self._send_lock:
            self.sock.sendall(self._frame(0x9))

    def _read(self, n):
        buf = self.rfile.read(n)
        if buf is None or len(buf) < n:
            raise WSClosed("Connection closed")
        return buf

    def recv(self):
        """Return the next complete text message. Raises socket.timeout if nothing arrives in time."""
        parts, started = [], False
        while True:
            b0, b1 = self._read(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if b1 & 0x80:                                  # servers should not mask, but accept it
                mask = self._read(4)
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._read(n)))
            else:
                data = self._read(n) if n else b""
            if opcode == 0x8:
                raise WSClosed("Server closed the connection")
            if opcode == 0x9:
                with self._send_lock:
                    self.sock.sendall(self._frame(0xA, data))
                continue
            if opcode == 0xA:
                return None                                # pong: proves the link is alive
            if opcode in (0x1, 0x2):
                parts, started = [data], True
            elif opcode == 0x0 and started:
                parts.append(data)
            if fin and started:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            if self.sock:
                try:
                    with self._send_lock:
                        self.sock.sendall(self._frame(0x8))
                except OSError:
                    pass
                self.sock.close()
        finally:
            self.sock = self.rfile = None


# ---------------------------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------------------------
class Feed:
    def __init__(self, finnhub_key="", ws_url=None, rest_base=None, yahoo=True):
        self.key = (finnhub_key or "").strip()
        self.ws_url = ws_url or FINNHUB_WS
        self.rest = rest_base or FINNHUB_REST
        self.yahoo = yahoo
        self.lock = threading.RLock()
        self.px = {}              # symbol -> quote dict
        self.want = {}            # symbol -> number of open pages watching it
        self.subs = set()         # queues of connected pages
        self.pending = set()      # symbols whose price changed since the last flush
        self.error = None
        self.unknown = set()
        self.pause_until = 0.0
        self.ws_connected = False
        self.ws_subscribed = set()
        self.ws_last_msg = 0.0
        self.ws_error = None
        self.calls = []           # timestamps of recent REST calls
        self._started = False

    # -- public --------------------------------------------------------------------------------
    @property
    def source(self):
        return "finnhub" if self.key else ("yahoo" if self.yahoo else None)

    def start(self):
        if self._started or not self.source:
            return
        self._started = True
        for fn in (self._poll_loop, self._flush_loop):
            threading.Thread(target=fn, daemon=True).start()
        if self.key:
            threading.Thread(target=self._ws_loop, daemon=True).start()

    def watch(self, symbols):
        syms = [s for s in symbols if s][:MAX_SYMBOLS]
        with self.lock:
            for s in syms:
                self.want[s] = self.want.get(s, 0) + 1
        return syms

    def unwatch(self, symbols):
        with self.lock:
            for s in symbols:
                if s in self.want:
                    self.want[s] -= 1
                    if self.want[s] <= 0:
                        del self.want[s]

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.subs.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def snapshot(self, symbols):
        with self.lock:
            return {s: self._public(self.px[s]) for s in symbols if s in self.px and "p" in self.px[s]}

    def status(self):
        with self.lock:
            now = time.time()
            recent = [t for t in self.calls if now - t < 60]
            return {
                "source": self.source, "delayed": self.source == "yahoo",
                "market": "open" if market_open() else "closed",
                "watching": len(self.want), "error": self.error, "unknown": sorted(self.unknown & set(self.want)),
                "ws": {"enabled": bool(self.key), "connected": self.ws_connected, "symbols": len(self.ws_subscribed),
                       "lastMessageAgo": round(now - self.ws_last_msg, 1) if self.ws_last_msg else None, "error": self.ws_error},
                "restCallsLastMinute": len(recent),
                "now": round(now * 1000),
            }

    # -- updates -------------------------------------------------------------------------------
    def _update(self, sym, price, prev_close=None, ts=None, src="", trade=False):
        if not price or price <= 0:
            return
        with self.lock:
            q = self.px.get(sym) or {}
            if not trade and ts and q.get("tradeAt") and ts * 1000 < q.get("t", 0):
                # a polled quote older than a trade already received: keep the newer price, take only the day-change base
                if prev_close:
                    q["pc"] = float(prev_close)
                    self.px[sym] = q
                    self.pending.add(sym)
                return
            changed = q.get("p") != price
            q["p"] = float(price)
            if prev_close:
                q["pc"] = float(prev_close)
            q["src"] = src
            q["t"] = int(ts * 1000) if ts else int(time.time() * 1000)     # time of the last trade, if known
            q["at"] = int(time.time() * 1000)                              # when this server last heard about it
            if trade:
                q["tradeAt"] = q["at"]
            self.px[sym] = q
            if changed or "sent" not in q:
                q["sent"] = True
                self.pending.add(sym)

    def _flush_loop(self):
        while True:
            time.sleep(0.25)
            with self.lock:
                if not self.pending:
                    continue
                msg = {"type": "tick", "prices": {s: self._public(self.px[s]) for s in self.pending if s in self.px}}
                self.pending = set()
                subs = list(self.subs)
            for q in subs:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    @staticmethod
    def _public(q):
        return {k: v for k, v in q.items() if k not in ("sent", "polled")}

    # -- REST polling --------------------------------------------------------------------------
    def _spacing(self):
        return 60.0 / REQUESTS_PER_MINUTE if self.key else 2.0

    def _interval(self, sym, n):
        """Seconds between polls of one symbol."""
        if not market_open():
            return 90.0
        with self.lock:
            q = self.px.get(sym) or {}
            streaming = self.ws_connected and q.get("tradeAt") and time.time() * 1000 - q["tradeAt"] < 120000
        if streaming:
            return 300.0                                    # trades already arrive; poll only to refresh the day change
        return max(3.0 if self.key else 15.0, n * self._spacing())

    def _poll_loop(self):
        while True:
            try:
                with self.lock:
                    syms = list(self.want)
                    last = {s: (self.px.get(s) or {}).get("polled", 0) for s in syms}
                now = time.time()
                if not syms or now < self.pause_until:
                    time.sleep(0.5)
                    continue
                due = [s for s in syms if now - last[s] >= self._interval(s, len(syms))]
                if not due:
                    time.sleep(0.5)
                    continue
                sym = min(due, key=lambda s: last[s])
                self._poll_one(sym)
                time.sleep(self._spacing())
            except Exception as e:                           # never let the poller thread die
                self.error = "poller: %s" % e
                time.sleep(2)

    def _note_call(self):
        with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60] + [now]

    def _poll_one(self, sym):
        with self.lock:
            self.px.setdefault(sym, {})["polled"] = time.time()
        self._note_call()
        try:
            if self.key:
                got = self._finnhub_quote(sym)
            else:
                got = self._yahoo_quote(sym)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.pause_until = time.time() + 30
                self.error = "The data provider is rate-limiting this key. Pausing polls for 30 seconds."
            elif e.code in (401, 403):
                self.error = "Finnhub rejected the API key (HTTP %d). Check FINNHUB_API_KEY in .env." % e.code
                self.pause_until = time.time() + 60
            else:
                self.error = "The data provider returned HTTP %d for %s." % (e.code, sym)
            return
        except (urllib.error.URLError, socket.timeout, ValueError, OSError) as e:
            self.error = "Could not reach the data provider: %s" % getattr(e, "reason", e)
            return
        if got is None:
            with self.lock:
                self.unknown.add(sym)       # one unknown symbol is not a feed problem
            return
        self.error = None
        with self.lock:
            self.unknown.discard(sym)
        price, pc, ts = got
        self._update(sym, price, pc, ts, src="finnhub" if self.key else "yahoo")

    def _get_json(self, url, headers=None, timeout=10):
        req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def _finnhub_quote(self, sym):
        d = self._get_json("%s/quote?symbol=%s" % (self.rest, urllib.parse.quote(sym)), {"X-Finnhub-Token": self.key})
        if not d or not d.get("c"):
            return None
        return float(d["c"]), (float(d["pc"]) if d.get("pc") else None), d.get("t")

    def _yahoo_quote(self, sym):
        d = self._get_json(YAHOO_CHART % urllib.parse.quote(sym))
        res = (d.get("chart", {}).get("result") or [None])[0]
        if not res:
            return None
        m = res.get("meta", {})
        price = m.get("regularMarketPrice")
        if not price:
            return None
        return float(price), m.get("chartPreviousClose") or m.get("previousClose"), m.get("regularMarketTime")

    # -- WebSocket -----------------------------------------------------------------------------
    def _ws_loop(self):
        backoff = 2.0
        while True:
            ws = WSClient("%s?token=%s" % (self.ws_url, urllib.parse.quote(self.key)))
            try:
                ws.connect()
                with self.lock:
                    self.ws_connected, self.ws_error, self.ws_subscribed = True, None, set()
                    self.ws_last_msg = time.time()
                backoff = 2.0
                stop = threading.Event()
                threading.Thread(target=self._ws_sync, args=(ws, stop), daemon=True).start()
                try:
                    self._ws_read(ws)
                finally:
                    stop.set()
            except (WSClosed, OSError, ssl.SSLError, socket.timeout) as e:
                self.ws_error = str(e) or e.__class__.__name__
            finally:
                ws.close()
                with self.lock:
                    self.ws_connected = False
                    self.ws_subscribed = set()
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _ws_read(self, ws):
        ws.sock.settimeout(25)
        while True:
            try:
                msg = ws.recv()
            except socket.timeout:
                if time.time() - self.ws_last_msg > 120:
                    raise WSClosed("No data for 2 minutes, reconnecting")
                ws.send_ping()                               # quiet market: check the link is alive
                continue
            self.ws_last_msg = time.time()
            if not msg:
                continue
            try:
                d = json.loads(msg)
            except ValueError:
                continue
            if d.get("type") == "trade":
                for t in d.get("data") or []:
                    # one message can carry several trades for a symbol; the last one is the latest
                    self._update(t.get("s"), t.get("p"), None, (t.get("t") or 0) / 1000.0 or None, src="finnhub-ws", trade=True)
            elif d.get("type") == "error":
                self.ws_error = str(d.get("msg") or "error")

    def _ws_sync(self, ws, stop):
        """Keep the WebSocket subscriptions equal to the symbols pages are watching."""
        while not stop.is_set():
            with self.lock:
                want = set(list(self.want)[:MAX_SYMBOLS])
                have = set(self.ws_subscribed)
            try:
                for s in want - have:
                    ws.send_text(json.dumps({"type": "subscribe", "symbol": s}))
                    with self.lock:
                        self.ws_subscribed.add(s)
                for s in have - want:
                    ws.send_text(json.dumps({"type": "unsubscribe", "symbol": s}))
                    with self.lock:
                        self.ws_subscribed.discard(s)
            except (OSError, ssl.SSLError, AttributeError):
                return
            stop.wait(1.0)
