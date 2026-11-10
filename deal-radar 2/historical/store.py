"""SQLite tables for the historical M&A research set."""
import os
import sqlite3
from datetime import datetime, timezone

TABLES = (
    "historical_ma_transactions",
    "historical_company_snapshots",
    "historical_stock_prices",
    "historical_deal_outcomes",
    "historical_news_signals",
)


def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS search_hits (
        adsh TEXT PRIMARY KEY,
        cik INTEGER,
        filer TEXT,
        search_ticker TEXT,
        form TEXT,
        filed_on TEXT,
        items TEXT,
        doc_url TEXT,
        query TEXT,
        sic TEXT,
        retrieved_at TEXT,
        text_status TEXT,
        role TEXT,
        role_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS ingest_windows (
        window_key TEXT PRIMARY KEY,
        status TEXT,
        hit_count INTEGER,
        note TEXT
    );
    CREATE TABLE IF NOT EXISTS historical_ma_transactions (
        adsh TEXT PRIMARY KEY,
        target_cik INTEGER,
        target_name TEXT,
        target_ticker TEXT,
        acquirer_name TEXT,
        acquirer_ticker TEXT,
        announcement_date TEXT,
        consideration TEXT,
        offer_price REAL,
        offer_sentence TEXT,
        exchange_ratio REAL,
        transaction_value REAL,
        transaction_value_sentence TEXT,
        role TEXT,
        role_reason TEXT,
        is_amendment INTEGER,
        duplicate_of TEXT,
        competing_adsh TEXT,
        filing_url TEXT,
        source TEXT,
        retrieved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS historical_deal_outcomes (
        adsh TEXT PRIMARY KEY,
        outcome TEXT,
        outcome_date TEXT,
        days_to_outcome INTEGER,
        evidence_adsh TEXT,
        evidence_sentence TEXT,
        hsr INTEGER,
        financing_condition INTEGER,
        shareholder_vote INTEGER,
        tender INTEGER,
        go_shop INTEGER,
        deregistration_form TEXT,
        deregistration_date TEXT,
        price_before REAL,
        price_before_date TEXT,
        price_day0 REAL,
        price_day0_date TEXT,
        price_day1 REAL,
        price_day1_date TEXT,
        price_day5 REAL,
        price_day5_date TEXT,
        price_day10 REAL,
        price_day10_date TEXT,
        price_day30 REAL,
        price_day30_date TEXT,
        price_source TEXT,
        observed_premium REAL,
        retrieved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS historical_stock_prices (
        ticker TEXT,
        bar_date TEXT,
        close REAL,
        adj_close REAL,
        volume REAL,
        source TEXT,
        retrieved_at TEXT,
        PRIMARY KEY (ticker, bar_date, source)
    );
    CREATE TABLE IF NOT EXISTS price_coverage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        cik INTEGER,
        historical_date TEXT,
        source TEXT,
        http_status INTEGER,
        status TEXT,
        detail TEXT,
        yahoo_name TEXT,
        yahoo_symbol TEXT,
        first_trade_date TEXT,
        bar_count INTEGER,
        gap_count INTEGER,
        retrieved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS historical_company_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cik INTEGER,
        ticker TEXT,
        snapshot_date TEXT,
        kind TEXT,
        announcement_adsh TEXT,
        announcement_date TEXT,
        label_30 INTEGER,
        label_90 INTEGER,
        label_180 INTEGER,
        last_close REAL,
        last_close_date TEXT,
        price_source TEXT,
        latest_10k_date TEXT,
        latest_10q_date TEXT,
        revenue REAL,
        revenue_filed TEXT,
        assets REAL,
        assets_filed TEXT,
        cash REAL,
        cash_filed TEXT,
        equity REAL,
        equity_filed TEXT,
        debt REAL,
        debt_filed TEXT,
        shares REAL,
        shares_filed TEXT,
        facts_status TEXT,
        company_outcome TEXT,
        retrieved_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_snap
        ON historical_company_snapshots(cik, snapshot_date, kind, ifnull(announcement_adsh, ''));
    CREATE TABLE IF NOT EXISTS historical_news_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cik INTEGER,
        ticker TEXT,
        published_at TEXT NOT NULL,
        retrieved_at TEXT,
        source TEXT NOT NULL,
        headline TEXT,
        sentiment REAL
    );
    CREATE TABLE IF NOT EXISTS provider_notes (
        name TEXT PRIMARY KEY,
        detail TEXT
    );
    CREATE TABLE IF NOT EXISTS company_facts_status (
        cik INTEGER PRIMARY KEY,
        status TEXT,
        detail TEXT,
        retrieved_at TEXT
    );
    """)
    conn.commit()


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mark_duplicates(conn):
    """One transaction per company per week. A later filing in that week is a duplicate.

    A second target filing 14 to 180 days later is marked as a competing filing.
    """
    from datetime import date
    conn.execute("UPDATE historical_ma_transactions SET duplicate_of=NULL, competing_adsh=NULL")
    rows = conn.execute(
        """SELECT adsh, target_cik, announcement_date FROM historical_ma_transactions
           WHERE role='target' AND is_amendment=0 AND target_cik IS NOT NULL
             AND announcement_date IS NOT NULL
           ORDER BY target_cik, announcement_date, adsh"""
    ).fetchall()
    primary = None
    previous = None
    for row in rows:
        day = date.fromisoformat(row["announcement_date"])
        if previous and previous["target_cik"] == row["target_cik"] and 0 <= (day - previous["day"]).days <= 7:
            conn.execute(
                "UPDATE historical_ma_transactions SET duplicate_of=? WHERE adsh=?",
                (primary["adsh"], row["adsh"]),
            )
        else:
            primary = {"adsh": row["adsh"], "target_cik": row["target_cik"], "day": day}
        previous = {"target_cik": row["target_cik"], "day": day}
    primary = conn.execute(
        """SELECT adsh, target_cik, announcement_date FROM historical_ma_transactions
           WHERE role='target' AND is_amendment=0 AND duplicate_of IS NULL
             AND target_cik IS NOT NULL AND announcement_date IS NOT NULL
           ORDER BY target_cik, announcement_date"""
    ).fetchall()
    by_cik = {}
    for row in primary:
        by_cik.setdefault(row["target_cik"], []).append(row)
    for group in by_cik.values():
        for index, row in enumerate(group):
            day = date.fromisoformat(row["announcement_date"])
            nearest, nearest_gap = None, None
            for other in group[index + 1:]:
                gap = (date.fromisoformat(other["announcement_date"]) - day).days
                if 14 <= gap <= 180 and (nearest_gap is None or gap < nearest_gap):
                    nearest, nearest_gap = other["adsh"], gap
            if nearest:
                conn.execute(
                    "UPDATE historical_ma_transactions SET competing_adsh=? WHERE adsh=?",
                    (nearest, row["adsh"]),
                )
    conn.commit()


def insert_news(conn, row):
    if not row.get("published_at") or not row.get("source"):
        raise ValueError("A news row needs a publication time and a source. Nothing was stored.")
    conn.execute(
        """INSERT INTO historical_news_signals
           (cik, ticker, published_at, retrieved_at, source, headline, sentiment)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (row.get("cik"), row.get("ticker"), row["published_at"], row.get("retrieved_at"),
         row["source"], row.get("headline"), row.get("sentiment")),
    )
