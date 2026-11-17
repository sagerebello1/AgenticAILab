"""Append-only storage for a future options-chain collector.

Nothing here fetches a chain. A missing timestamp is stored as missing.
Snapshots are inserted, never updated.

The last-trade time and the collection time are different clocks. A contract
can keep the same last-trade time while the bid and ask change. Those are
separate observations. A missing last-trade time stays missing.

Uniqueness:

- One observation is the data source, contract symbol, expiration, and
  collection time. Repeating that combination is skipped and the stored row
  is left as it was.
- A different collection time is a new snapshot, even when the last-trade
  time and the contract are unchanged.
- A different expiration or a different data source is a new snapshot.
- The last-trade time is not part of the key, and it is never filled in to
  make a key.
- A collection run is the same attempt when the ticker, source, collection
  time, status, HTTP status, and reason all match. A different attempt is
  kept. Runs are not updated in place.
"""
import sqlite3


def init(conn):
    """Create the options tables. Does not touch daily stock prices."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS option_chain_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        collected_at TEXT NOT NULL,
        source TEXT NOT NULL,
        http_status INTEGER,
        status TEXT NOT NULL,
        reason TEXT
    );
    CREATE TABLE IF NOT EXISTS option_chain_quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_symbol TEXT NOT NULL,
        ticker TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('put', 'call')),
        strike REAL,
        expiration TEXT,
        bid REAL,
        ask REAL,
        last_price REAL,
        last_trade_at TEXT,
        volume REAL,
        open_interest REAL,
        implied_volatility REAL,
        underlying_price REAL,
        underlying_quote_at TEXT,
        collected_at TEXT NOT NULL,
        source TEXT NOT NULL
    );
    DROP INDEX IF EXISTS ux_option_quote_trade;
    DROP INDEX IF EXISTS ux_option_quote_collected;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_option_quote_observation
        ON option_chain_quotes(source, contract_symbol, expiration, collected_at)
        WHERE expiration IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_option_quote_observation_no_expiration
        ON option_chain_quotes(source, contract_symbol, collected_at)
        WHERE expiration IS NULL;
    """)
    conn.commit()


def _text(value, label):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ValueError("%s is missing." % label)
    return text


def _required(value, label):
    text = _text(value, label)
    if text is None:
        raise ValueError("%s is missing." % label)
    return text


def _number(value, label):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("%s is not a number." % label)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s is not a number." % label)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("%s is not a finite number." % label)
    return number


def _same(left, right):
    return left == right


def insert_run(conn, ticker, collected_at, source, status, http_status=None, reason=None):
    """Record one collection attempt. A repeat of the same attempt is skipped."""
    ticker = _required(ticker, "ticker")
    collected_at = _required(collected_at, "collected_at")
    source = _required(source, "source")
    status = _required(status, "status")
    reason = _text(reason, "reason")
    if http_status is not None:
        http_status = int(http_status)
    existing = conn.execute(
        """SELECT id, http_status, reason FROM option_chain_runs
           WHERE ticker=? AND collected_at=? AND source=? AND status=?""",
        (ticker, collected_at, source, status),
    ).fetchall()
    for row in existing:
        if _same(row["http_status"], http_status) and _same(row["reason"], reason):
            return {"inserted": False, "id": row["id"], "duplicate": True}
    cursor = conn.execute(
        """INSERT INTO option_chain_runs
           (ticker, collected_at, source, http_status, status, reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticker, collected_at, source, http_status, status, reason),
    )
    conn.commit()
    return {"inserted": True, "id": cursor.lastrowid, "duplicate": False}


def _existing_quote(conn, source, contract, expiration, collected_at):
    """Find the stored observation for this collection, if there is one."""
    if expiration is None:
        return conn.execute(
            """SELECT id FROM option_chain_quotes
               WHERE source=? AND contract_symbol=? AND collected_at=?
                 AND expiration IS NULL""",
            (source, contract, collected_at),
        ).fetchone()
    return conn.execute(
        """SELECT id FROM option_chain_quotes
           WHERE source=? AND contract_symbol=? AND collected_at=?
             AND expiration=?""",
        (source, contract, collected_at, expiration),
    ).fetchone()


def insert_quote(conn, quote):
    """Insert one contract observation. Never updates an existing row."""
    quote = quote or {}
    contract = _required(quote.get("contract_symbol"), "contract_symbol")
    ticker = _required(quote.get("ticker"), "ticker")
    kind = _required(quote.get("kind"), "kind").lower()
    if kind not in ("put", "call"):
        raise ValueError("kind must be put or call.")
    collected_at = _required(quote.get("collected_at"), "collected_at")
    source = _required(quote.get("source"), "source")
    last_trade_at = _text(quote.get("last_trade_at"), "last_trade_at")
    expiration = _text(quote.get("expiration"), "expiration")
    row = (
        contract, ticker, kind,
        _number(quote.get("strike"), "strike"),
        expiration,
        _number(quote.get("bid"), "bid"),
        _number(quote.get("ask"), "ask"),
        _number(quote.get("last_price"), "last_price"),
        last_trade_at,
        _number(quote.get("volume"), "volume"),
        _number(quote.get("open_interest"), "open_interest"),
        _number(quote.get("implied_volatility"), "implied_volatility"),
        _number(quote.get("underlying_price"), "underlying_price"),
        _text(quote.get("underlying_quote_at"), "underlying_quote_at"),
        collected_at, source,
    )
    existing = _existing_quote(conn, source, contract, expiration, collected_at)
    if existing is not None:
        return {"inserted": False, "id": existing["id"], "duplicate": True}
    try:
        cursor = conn.execute(
            """INSERT INTO option_chain_quotes (
                   contract_symbol, ticker, kind, strike, expiration, bid, ask, last_price,
                   last_trade_at, volume, open_interest, implied_volatility, underlying_price,
                   underlying_quote_at, collected_at, source
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        conn.commit()
    except sqlite3.IntegrityError:
        found = _existing_quote(conn, source, contract, expiration, collected_at)
        return {"inserted": False, "id": None if found is None else found["id"], "duplicate": True}
    return {"inserted": True, "id": cursor.lastrowid, "duplicate": False}
