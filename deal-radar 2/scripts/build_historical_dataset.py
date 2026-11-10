"""Build the historical M&A research tables. Does not train a model.

    python3 scripts/build_historical_dataset.py --start 2016-01-01

Search windows and downloaded filings are kept, so a second run continues
where the first one stopped. Prices that a source does not return stay blank.
"""
import argparse
import gzip
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "training"))

import edgar  # noqa: E402
import terms  # noqa: E402
from common import user_agent  # noqa: E402
from historical import facts as factmod  # noqa: E402
from historical import outcomes as outmod  # noqa: E402
from historical import prices as pricemod  # noqa: E402
from historical import report as reportmod  # noqa: E402
from historical.labels import control_label, label_set  # noqa: E402
from historical.prices import calendar_gaps, last_bar_on_or_before, listing_decision, trading_offset  # noqa: E402
from historical.providers import SourceError, financial_modeling_prep_bars, polygon_bars, stooq_status  # noqa: E402
from historical.store import connect, init, insert_news, mark_duplicates, now  # noqa: E402
from historical.text import plain_text, read_filing  # noqa: E402

DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
TEXT = os.path.join(ROOT, "data", "historical", "text")
SUBS = os.path.join(ROOT, "data", "historical", "submissions")
FACTS = os.path.join(ROOT, "data", "historical", "facts")
MERGER_QUERIES = ('"merge with and into"', '"merged with and into"')
TENDER_QUERY = '"cash tender offer"'
QUERIES = MERGER_QUERIES + (TENDER_QUERY,)
VERIFIED = """role='target' AND is_amendment=0 AND duplicate_of IS NULL"""


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def windows(start, end, span=7):
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=span - 1), end)
        yield cur, win_end
        cur = win_end + timedelta(days=1)


def parse_hit(hit, query):
    src = hit.get("_source") or {}
    adsh = src.get("adsh")
    ciks = src.get("ciks") or []
    if not adsh or not ciks:
        return None
    names = [edgar._parse_name(name) for name in src.get("display_names") or []]
    filer, ticker, _cik = names[0] if names else (None, None, None)
    filed = src.get("file_date")
    form = src.get("form") or src.get("file_type")
    ident = hit.get("_id") or ""
    filename = ident.split(":", 1)[1] if ":" in ident else None
    cik = int(ciks[0])
    nodash = adsh.replace("-", "")
    doc = ("%s/%d/%s/%s" % (edgar.ARCHIVES, cik, nodash, filename)) if filename else None
    sics = src.get("sics") or []
    return {
        "adsh": adsh, "cik": cik, "filer": filer, "search_ticker": ticker, "form": form,
        "filed_on": filed, "items": ",".join(src.get("items") or []), "doc_url": doc,
        "query": query, "sic": sics[0] if sics else None,
    }


def search(conn, ua, start, end):
    os.makedirs(TEXT, exist_ok=True)
    for query in QUERIES:
        for win_start, win_end in windows(start, end):
            key = "%s|%s|%s" % (query, win_start.isoformat(), win_end.isoformat())
            done = conn.execute("SELECT status FROM ingest_windows WHERE window_key=?", (key,)).fetchone()
            if done and done["status"] == "done":
                continue
            try:
                rows, total = search_window(ua, win_start, win_end, query)
            except edgar.EdgarError as exc:
                conn.execute(
                    "INSERT OR REPLACE INTO ingest_windows (window_key, status, hit_count, note) VALUES (?, ?, ?, ?)",
                    (key, "error", 0, str(exc)[:300]),
                )
                conn.commit()
                print("search error", key, file=sys.stderr)
                continue
            for row in rows:
                conn.execute(
                    """INSERT OR IGNORE INTO search_hits
                       (adsh, cik, filer, search_ticker, form, filed_on, items, doc_url, query, sic, retrieved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["adsh"], row["cik"], row["filer"], row["search_ticker"], row["form"], row["filed_on"],
                     row["items"], row["doc_url"], row["query"], row["sic"], iso_now()),
                )
            note = None if len(rows) >= total or total == 0 else "page union %d of reported %d" % (len(rows), total)
            conn.execute(
                "INSERT OR REPLACE INTO ingest_windows (window_key, status, hit_count, note) VALUES (?, ?, ?, ?)",
                (key, "done", len(rows), note),
            )
            conn.commit()
            print("search %s %s hits %d reported %d" % (win_start, query, len(rows), total))


def search_window(ua, start, end, query):
    offset, total, seen, rows = 0, 1, set(), []
    while offset < total and offset < 2000:
        params = {
            "q": query, "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
            "forms": "8-K", "from": str(offset),
        }
        payload = json.loads(edgar._get(edgar.SEARCH_URL + "?" + urllib.parse.urlencode(params), ua))
        total = ((payload.get("hits") or {}).get("total") or {}).get("value") or 0
        hits = (payload.get("hits") or {}).get("hits") or []
        if not hits:
            break
        added = 0
        for hit in hits:
            row = parse_hit(hit, query)
            if not row or row["adsh"] in seen:
                continue
            seen.add(row["adsh"])
            rows.append(row)
            added += 1
        if added == 0:
            break
        offset += 100
    if len(rows) < total:
        params["from"] = str(max(0, total - 100))
        try:
            payload = json.loads(edgar._get(edgar.SEARCH_URL + "?" + urllib.parse.urlencode(params), ua))
        except edgar.EdgarError:
            return rows, total
        for hit in (payload.get("hits") or {}).get("hits") or []:
            row = parse_hit(hit, query)
            if not row or row["adsh"] in seen:
                continue
            seen.add(row["adsh"])
            rows.append(row)
    return rows, total


def text_path(adsh):
    return os.path.join(TEXT, adsh + ".txt.gz")


def load_text(adsh):
    path = text_path(adsh)
    if os.path.exists(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return handle.read()
        except (OSError, EOFError, gzip.BadGzipFile):
            return None
    for folder in ("preannouncement_prototype/filings", "closing_validation/announcements"):
        alt = os.path.join(ROOT, "data", folder, adsh + ".txt")
        if os.path.exists(alt):
            return open(alt, encoding="utf-8", errors="replace").read()
    return None


class DiskFull(Exception):
    pass


def save_text(adsh, text):
    os.makedirs(TEXT, exist_ok=True)
    try:
        with gzip.open(text_path(adsh), "wt", encoding="utf-8") as handle:
            handle.write(text[:250000])
    except OSError as exc:
        if exc.errno == 28:
            raise DiskFull("No space left for filing text.")
        raise


def classify(conn, ua, per_year, max_filings):
    conn.execute("UPDATE search_hits SET text_status=NULL, role=NULL, role_reason=NULL WHERE role_reason='empty filing'")
    conn.execute(
        """UPDATE historical_ma_transactions
           SET role='spac_vehicle', role_reason='acquisition-company filer is not counted as a target'
           WHERE role='target' AND target_name LIKE '%Acquisition Corp%'"""
    )
    conn.commit()
    read_now = 0
    for kind, queries, cap in (
        ("merger", MERGER_QUERIES, per_year),
        ("tender", (TENDER_QUERY,), max(40, per_year // 5)),
    ):
        years = [row[0] for row in conn.execute(
            "SELECT DISTINCT substr(filed_on, 1, 4) FROM search_hits WHERE query IN (%s) AND filed_on IS NOT NULL ORDER BY 1"
            % ",".join("?" * len(queries)), queries)]
        for year in years:
            already = conn.execute(
                """SELECT COUNT(*) FROM search_hits
                   WHERE substr(filed_on,1,4)=? AND text_status='read' AND query IN (%s)"""
                % ",".join("?" * len(queries)), (year,) + tuple(queries)).fetchone()[0]
            room = cap - already
            if room <= 0:
                continue
            pending = conn.execute(
                """SELECT * FROM search_hits
                   WHERE substr(filed_on,1,4)=? AND text_status IS NULL AND query IN (%s)
                     AND form NOT LIKE '%%/A' AND items LIKE '%%1.01%%' AND doc_url IS NOT NULL
                   ORDER BY filed_on LIMIT ?"""
                % ",".join("?" * len(queries)),
                (year,) + tuple(queries) + (room,),
            ).fetchall()
            for hit in pending:
                if max_filings and read_now >= max_filings:
                    conn.commit()
                    print("classify stopped at --max-filings", max_filings)
                    return
                try:
                    saved = read_one(conn, ua, hit)
                except DiskFull as exc:
                    conn.commit()
                    print(exc)
                    return
                if not saved:
                    continue
                read_now += 1
                if read_now % 25 == 0:
                    conn.commit()
                    print("classified", read_now, kind, year)
            conn.commit()
    print("classified this run", read_now)


def form_text(ua, hit):
    """The 8-K itself. A search hit often points at an exhibit that has no Item 1.01."""
    index = "%s/%d/%s/%s-index.htm" % (
        edgar.ARCHIVES, int(hit["cik"]), hit["adsh"].replace("-", ""), hit["adsh"])
    try:
        docs = edgar.list_documents(ua, index)
    except edgar.EdgarError:
        return None
    for doc in docs:
        if (doc.get("type") or "").upper().startswith("8-K"):
            try:
                return edgar.fetch_document(ua, doc["url"], max_bytes=2_000_000).decode("utf-8", "replace")
            except edgar.EdgarError:
                return None
    return None


def read_one(conn, ua, hit):
    adsh = hit["adsh"]
    text = load_text(adsh)
    if text is None or "item 1.01" not in plain_text(text).lower():
        body = form_text(ua, hit)
        if body and "item 1.01" in plain_text(body).lower():
            text = body
            save_text(adsh, text)
        elif text is None and hit["doc_url"]:
            try:
                text = edgar.fetch_document(ua, hit["doc_url"], max_bytes=2_000_000).decode("utf-8", "replace")
            except edgar.EdgarError as exc:
                conn.execute(
                    "UPDATE search_hits SET text_status='error', role_reason=? WHERE adsh=?",
                    (str(exc)[:240], adsh),
                )
                return False
            save_text(adsh, text)
    if not text:
        conn.execute(
            "UPDATE search_hits SET text_status='error', role_reason='no filing text' WHERE adsh=?",
            (adsh,),
        )
        return False
    parsed = read_filing(text, hit["filer"] or "")
    conn.execute(
        "UPDATE search_hits SET text_status='read', role=?, role_reason=? WHERE adsh=?",
        (parsed["role"], parsed["roleReason"], adsh),
    )
    if parsed["role"] not in ("target", "buyer"):
        return True
    amendment = 1 if (hit["form"] or "").upper().find("/A") >= 0 else 0
    cik = parsed["registrantCik"] or hit["cik"]
    if parsed["role"] == "target":
        target_cik, target_name, target_ticker = cik, hit["filer"], parsed["ticker"] or hit["search_ticker"]
        acquirer_name, acquirer_ticker = parsed["acquirerName"], parsed["acquirerTicker"]
    else:
        target_cik, target_name, target_ticker = None, None, None
        acquirer_name = hit["filer"]
        acquirer_ticker = parsed["ticker"] or hit["search_ticker"]
    conn.execute(
        """INSERT OR REPLACE INTO historical_ma_transactions (
            adsh, target_cik, target_name, target_ticker, acquirer_name, acquirer_ticker,
            announcement_date, consideration, offer_price, offer_sentence, exchange_ratio,
            transaction_value, transaction_value_sentence, role, role_reason, is_amendment,
            filing_url, source, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (adsh, target_cik, target_name, target_ticker, acquirer_name, acquirer_ticker,
         hit["filed_on"], parsed["consideration"], parsed["offer"], parsed["offerSentence"],
         parsed["exchangeRatio"], parsed["transactionValue"], parsed["transactionValueSentence"],
         parsed["role"], parsed["roleReason"], amendment, hit["doc_url"],
         "sec-edgar:" + (hit["query"] or ""), iso_now()),
    )
    return True


def load_submissions(ua, cik):
    os.makedirs(SUBS, exist_ok=True)
    path = os.path.join(SUBS, "%d.json" % int(cik))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    alt = os.path.join(ROOT, "data", "closing_validation", "submissions", "%d.json" % int(cik))
    if os.path.exists(alt):
        with open(alt, encoding="utf-8") as handle:
            payload = json.load(handle)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return payload
    payload = edgar.submissions(ua, cik)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return payload


def outcome_url(cik, adsh, doc):
    if not doc:
        return None
    return "%s/%d/%s/%s" % (edgar.ARCHIVES, int(cik), adsh.replace("-", ""), doc)


def outcomes(conn, ua, limit):
    rows = conn.execute(
        """SELECT adsh, target_cik, announcement_date FROM historical_ma_transactions
           WHERE %s AND target_cik IS NOT NULL ORDER BY announcement_date""" % VERIFIED
    ).fetchall()
    done = 0
    for row in rows:
        if limit and done >= limit:
            break
        existing = conn.execute(
            "SELECT outcome FROM historical_deal_outcomes WHERE adsh=?", (row["adsh"],)
        ).fetchone()
        if existing and existing["outcome"] in ("closed", "terminated", "conflict"):
            continue
        record_outcome(conn, ua, row)
        done += 1
        if done % 20 == 0:
            conn.commit()
            print("outcomes", done)
    conn.commit()
    print("outcomes this run", done)


def record_outcome(conn, ua, row):
    try:
        sub = load_submissions(ua, row["target_cik"])
    except edgar.EdgarError as exc:
        conn.execute(
            """INSERT OR REPLACE INTO historical_deal_outcomes
               (adsh, outcome, evidence_sentence, retrieved_at) VALUES (?, 'unresolved', ?, ?)""",
            (row["adsh"], str(exc)[:240], iso_now()),
        )
        return
    announcement = row["announcement_date"]
    later = []
    dereg_form, dereg_date = None, None
    for filing in sub.get("filings") or []:
        filed = filing.get("date") or ""
        if filed <= announcement:
            continue
        form = filing.get("form") or ""
        if dereg_date is None and (form.startswith("15") or form.startswith("25")):
            dereg_form, dereg_date = form, filed
        items = filing.get("items") or []
        if form.startswith("8-K") and filed <= add_days(announcement, 800) and ("2.01" in items or "1.02" in items):
            later.append(filing)
    decision, evidence, evidence_adsh, outcome_date = "unresolved", None, None, None
    seen = set()
    for filing in later[:4]:
        url = outcome_url(row["target_cik"], filing["adsh"], filing.get("doc"))
        if not url or filing["adsh"] in seen or filing["adsh"] == row["adsh"]:
            continue
        seen.add(filing["adsh"])
        text = load_text(filing["adsh"])
        if text is None:
            try:
                text = edgar.fetch_document(ua, url, max_bytes=1_500_000).decode("utf-8", "replace")
            except edgar.EdgarError:
                continue
            save_text(filing["adsh"], text)
        found, sentence = outmod.outcome_from_text(text)
        if found == "unresolved":
            continue
        if decision not in ("unresolved", found):
            decision, evidence, evidence_adsh, outcome_date = "conflict", sentence, filing["adsh"], filing["date"]
            break
        decision, evidence, evidence_adsh, outcome_date = found, sentence, filing["adsh"], filing["date"]
    flags = announcement_flags(row["adsh"])
    days = None
    if outcome_date and decision in ("closed", "terminated"):
        days = (date.fromisoformat(outcome_date) - date.fromisoformat(announcement)).days
    conn.execute(
        """INSERT OR REPLACE INTO historical_deal_outcomes (
            adsh, outcome, outcome_date, days_to_outcome, evidence_adsh, evidence_sentence,
            hsr, financing_condition, shareholder_vote, tender, go_shop,
            deregistration_form, deregistration_date, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row["adsh"], decision, outcome_date, days, evidence_adsh, evidence, flags["hsr"],
         flags["financing"], flags["vote"], flags["tender"], flags["goShop"],
         dereg_form, dereg_date, iso_now()),
    )


def announcement_flags(adsh):
    text = load_text(adsh) or ""
    flags = (terms.extract_terms(plain_text(text)).get("flags") or {}) if text else {}
    def bit(value):
        if value is True:
            return 1
        if value is False:
            return 0
        return None
    return {
        "hsr": 1 if flags.get("hsr") else 0,
        "financing": bit(flags.get("financingCondition")),
        "vote": 1 if flags.get("vote") else 0,
        "tender": 1 if flags.get("tender") else 0,
        "goShop": 1 if flags.get("goShop") else 0,
    }


def add_days(iso, days):
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def phrase_hits(ua, cik, start, end, query):
    params = {
        "q": query, "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
        "forms": "8-K", "ciks": "%010d" % int(cik),
    }
    payload = json.loads(edgar._get(edgar.SEARCH_URL + "?" + urllib.parse.urlencode(params), ua))
    total = ((payload.get("hits") or {}).get("total") or {}).get("value") or 0
    hits = (payload.get("hits") or {}).get("hits") or []
    dates = []
    for hit in hits:
        filed = ((hit.get("_source") or {}).get("file_date"))
        if filed:
            dates.append(date.fromisoformat(filed))
    if total > len(hits):
        return None
    return dates


def controls(conn, ua, per_week):
    if per_week <= 0:
        print("controls skipped")
        return
    target_ciks = {row[0] for row in conn.execute(
        "SELECT DISTINCT target_cik FROM historical_ma_transactions WHERE %s AND target_cik IS NOT NULL" % VERIFIED
    )}
    added = 0
    for year in range(2021, 2025):
        for month in (2, 5, 8, 11):
            start = date(year, month, 1)
            end = start + timedelta(days=6)
            key = "control|%s" % start.isoformat()
            if conn.execute("SELECT status FROM ingest_windows WHERE window_key=?", (key,)).fetchone():
                continue
            try:
                hits, _total = search_form(ua, start, end, '"consolidated balance sheets"', "10-K")
            except edgar.EdgarError as exc:
                print("control search error", start, exc, file=sys.stderr)
                continue
            kept = 0
            for hit in hits:
                if kept >= per_week:
                    break
                if hit["cik"] in target_ciks:
                    continue
                if conn.execute(
                    "SELECT id FROM historical_company_snapshots WHERE cik=? AND kind='non_acquired'",
                    (hit["cik"],),
                ).fetchone():
                    continue
                snapshot = date.fromisoformat(hit["filed_on"])
                if snapshot + timedelta(days=180) > date.today():
                    continue
                dates, clear = screen_control(ua, hit["cik"], snapshot)
                if not clear:
                    continue
                save_control(conn, ua, hit, snapshot, dates)
                kept += 1
                added += 1
            conn.execute(
                "INSERT OR REPLACE INTO ingest_windows (window_key, status, hit_count, note) VALUES (?, 'done', ?, ?)",
                (key, kept, None),
            )
            conn.commit()
            print("controls", start, kept)
    print("controls this run", added)


def search_form(ua, start, end, query, forms):
    params = {
        "q": query, "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
        "forms": forms,
    }
    payload = json.loads(edgar._get(edgar.SEARCH_URL + "?" + urllib.parse.urlencode(params), ua))
    total = ((payload.get("hits") or {}).get("total") or {}).get("value") or 0
    rows = []
    for hit in (payload.get("hits") or {}).get("hits") or []:
        row = parse_hit(hit, query)
        if row and row["filed_on"]:
            rows.append(row)
    return rows, total


def screen_control(ua, cik, snapshot):
    found = []
    for query in QUERIES:
        try:
            dates = phrase_hits(ua, cik, snapshot, snapshot + timedelta(days=180), query)
        except edgar.EdgarError:
            return [], False
        if dates is None:
            return [], False
        found.extend(dates)
    return found, True


def save_control(conn, ua, hit, snapshot, hit_dates):
    labels = {days: control_label(snapshot, hit_dates, days, date.today()) for days in (30, 90, 180)}
    last_filing, tickers, dereg = None, [], None
    try:
        sub = load_submissions(ua, hit["cik"])
        filings = sub.get("filings") or []
        if filings:
            last_filing = max(item["date"] for item in filings if item.get("date"))
        tickers = sub.get("tickers") or []
        for item in filings:
            form = item.get("form") or ""
            if item.get("date") and item["date"] >= snapshot.isoformat() and (form.startswith("15") or form.startswith("25")):
                dereg = "%s %s" % (form, item["date"])
                break
    except edgar.EdgarError:
        sub = None
    outcome = "no phrase hit for the merger queries in the next 180 days"
    if not tickers:
        outcome += "; not in the current SEC ticker list"
    if dereg:
        outcome += "; " + dereg
    if last_filing:
        outcome += "; last filing " + last_filing
    conn.execute(
        """INSERT OR REPLACE INTO historical_company_snapshots (
            cik, ticker, snapshot_date, kind, label_30, label_90, label_180,
            facts_status, company_outcome, retrieved_at
        ) VALUES (?, ?, ?, 'non_acquired', ?, ?, ?, 'pending', ?, ?)""",
        (hit["cik"], hit["search_ticker"], snapshot.isoformat(), labels[30], labels[90], labels[180],
         outcome, iso_now()),
    )


def prices(conn, ua):
    wanted = {}
    for row in conn.execute(
        """SELECT target_ticker, target_cik, announcement_date FROM historical_ma_transactions
           WHERE %s AND target_ticker IS NOT NULL AND announcement_date IS NOT NULL""" % VERIFIED
    ):
        wanted.setdefault(row["target_ticker"], []).append(("target", row["target_cik"], row["announcement_date"]))
    for row in conn.execute(
        """SELECT ticker, cik, snapshot_date FROM historical_company_snapshots
           WHERE kind='non_acquired' AND ticker IS NOT NULL"""
    ):
        wanted.setdefault(row["ticker"], []).append(("control", row["cik"], row["snapshot_date"]))
    done = 0
    for ticker, uses in wanted.items():
        if conn.execute("SELECT id FROM price_coverage WHERE ticker=? AND source='yahoo-chart'", (ticker,)).fetchone():
            continue
        historical = min(date.fromisoformat(item[2]) for item in uses)
        start = historical - timedelta(days=420)
        end = min(date.today(), max(date.fromisoformat(item[2]) for item in uses) + timedelta(days=70))
        if any(item[0] == "control" for item in uses) and not any(item[0] == "target" for item in uses):
            end = min(end, max(date.fromisoformat(item[2]) for item in uses))
        store_prices(conn, ticker, uses[0][1], historical, start, end)
        done += 1
        if done % 25 == 0:
            conn.commit()
            print("prices", done)
    conn.commit()
    print("prices this run", done)


def store_prices(conn, ticker, cik, historical, start, end):
    try:
        parsed = pricemod.fetch_yahoo(ticker, start, end)
    except SourceError as exc:
        coverage(conn, ticker, cik, historical, None, "request_failed", str(exc), {}, 0, 0)
        return
    meta = parsed.get("meta") or {}
    if not meta.get("firstTradeDate"):
        try:
            probe = pricemod.fetch_yahoo_meta(ticker)
        except SourceError:
            probe = {"meta": {}, "httpStatus": None}
        if probe.get("meta"):
            meta = probe["meta"]
    decision = listing_decision(meta, historical, ticker) if meta else "no_listing"
    bars = parsed["bars"] if decision == "ok" and parsed.get("httpStatus") == 200 else []
    bars = [bar for bar in bars if start <= bar["date"] <= end]
    first = None
    if meta.get("firstTradeDate"):
        first = datetime.fromtimestamp(int(meta["firstTradeDate"]), tz=timezone.utc).date().isoformat()
    detail = parsed.get("error") or decision
    name = meta.get("longName") or meta.get("shortName")
    coverage(conn, ticker, cik, historical, parsed.get("httpStatus"), decision if bars or decision != "ok" else "no_bars",
             detail, {"name": name, "symbol": meta.get("symbol"), "first": first}, len(bars), len(calendar_gaps(bars)))
    for bar in bars:
        conn.execute(
            """INSERT OR REPLACE INTO historical_stock_prices
               (ticker, bar_date, close, adj_close, volume, source, retrieved_at)
               VALUES (?, ?, ?, ?, ?, 'yahoo-chart', ?)""",
            (ticker, bar["date"].isoformat(), bar["close"], bar["adjClose"], bar["volume"], iso_now()),
        )


def coverage(conn, ticker, cik, historical, http_status, status, detail, meta, bar_count, gap_count):
    conn.execute(
        """INSERT INTO price_coverage (
            ticker, cik, historical_date, source, http_status, status, detail,
            yahoo_name, yahoo_symbol, first_trade_date, bar_count, gap_count, retrieved_at
        ) VALUES (?, ?, ?, 'yahoo-chart', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, cik, historical.isoformat(), http_status, status, (detail or "")[:300],
         meta.get("name"), meta.get("symbol"), meta.get("first"), bar_count, gap_count, iso_now()),
    )


def slim_facts(payload):
    """Keep only the tags the snapshots read. The full companyfacts file is not stored."""
    tags = {
        "us-gaap": (
            "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "Assets", "CashAndCashEquivalentsAtCarryingValue", "Cash", "StockholdersEquity",
            "LongTermDebtNoncurrent", "LongTermDebt",
        ),
        "dei": ("EntityCommonStockSharesOutstanding",),
    }
    kept = {"facts": {}}
    source = (payload or {}).get("facts") or {}
    for namespace, names in tags.items():
        bucket = source.get(namespace) or {}
        kept["facts"][namespace] = {name: bucket[name] for name in names if name in bucket}
    return kept


def facts(conn, ua, limit):
    os.makedirs(FACTS, exist_ok=True)
    ciks = [row[0] for row in conn.execute(
        """SELECT DISTINCT target_cik FROM historical_ma_transactions
           WHERE %s AND target_cik IS NOT NULL
           UNION
           SELECT DISTINCT cik FROM historical_company_snapshots WHERE kind='non_acquired'""" % VERIFIED
    )]
    done = 0
    for cik in ciks:
        if limit and done >= limit:
            break
        if conn.execute("SELECT cik FROM company_facts_status WHERE cik=?", (cik,)).fetchone():
            continue
        path = os.path.join(FACTS, "%d.json" % int(cik))
        url = "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % int(cik)
        try:
            raw = edgar._get(url, ua, max_bytes=8_000_000, timeout=45)
            payload = json.loads(raw)
        except (edgar.EdgarError, json.JSONDecodeError, ValueError, OSError) as exc:
            conn.execute(
                "INSERT OR REPLACE INTO company_facts_status (cik, status, detail, retrieved_at) VALUES (?, 'missing', ?, ?)",
                (cik, str(exc)[:240], iso_now()),
            )
            done += 1
            continue
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(slim_facts(payload), handle)
        except OSError as exc:
            print("facts stopped:", exc)
            break
        conn.execute(
            "INSERT OR REPLACE INTO company_facts_status (cik, status, detail, retrieved_at) VALUES (?, 'stored', NULL, ?)",
            (cik, iso_now()),
        )
        done += 1
        if done % 20 == 0:
            conn.commit()
            print("facts", done)
    conn.commit()
    print("facts this run", done)


def snapshots(conn):
    conn.execute("DELETE FROM historical_company_snapshots WHERE kind='target_pre'")
    today = date.today()
    for row in conn.execute(
        """SELECT adsh, target_cik, target_ticker, announcement_date FROM historical_ma_transactions
           WHERE %s AND announcement_date IS NOT NULL AND target_cik IS NOT NULL""" % VERIFIED
    ):
        announcement = date.fromisoformat(row["announcement_date"])
        bars = load_bars(conn, row["target_ticker"])
        sub = read_cached_submissions(row["target_cik"])
        fact_file = read_cached_facts(row["target_cik"])
        for horizon in (30, 90, 180):
            snapshot = announcement - timedelta(days=horizon)
            labels = label_set(snapshot, announcement, today)
            write_snapshot(conn, row["target_cik"], row["target_ticker"], snapshot, "target_pre",
                           row["adsh"], row["announcement_date"], labels, bars, sub, fact_file,
                           "acquisition announced after this snapshot")
    refresh_control_features(conn)
    conn.commit()


def refresh_control_features(conn):
    rows = conn.execute("SELECT * FROM historical_company_snapshots WHERE kind='non_acquired'").fetchall()
    for row in rows:
        snapshot = date.fromisoformat(row["snapshot_date"])
        bars = load_bars(conn, row["ticker"])
        chosen = last_bar_on_or_before(bars, snapshot) if bars else None
        sub = read_cached_submissions(row["cik"])
        fact_file = read_cached_facts(row["cik"])
        ten_k = latest_statement(sub, snapshot, "10-K")
        ten_q = latest_statement(sub, snapshot, "10-Q")
        figures = factmod.statement_facts(fact_file, snapshot.isoformat()) if fact_file else {}
        conn.execute(
            """UPDATE historical_company_snapshots SET
                last_close=?, last_close_date=?, price_source=?, latest_10k_date=?, latest_10q_date=?,
                revenue=?, revenue_filed=?, assets=?, assets_filed=?, cash=?, cash_filed=?,
                equity=?, equity_filed=?, debt=?, debt_filed=?, shares=?, shares_filed=?, facts_status=?
               WHERE id=?""",
            feature_tuple(chosen, ten_k, ten_q, figures, "stored" if fact_file else row["facts_status"]) + (row["id"],),
        )


def write_snapshot(conn, cik, ticker, snapshot, kind, adsh, announcement, labels, bars, sub, fact_file, outcome):
    chosen = last_bar_on_or_before(bars, snapshot) if bars else None
    ten_k = latest_statement(sub, snapshot, "10-K")
    ten_q = latest_statement(sub, snapshot, "10-Q")
    figures = factmod.statement_facts(fact_file, snapshot.isoformat()) if fact_file else {}
    conn.execute(
        """INSERT INTO historical_company_snapshots (
            cik, ticker, snapshot_date, kind, announcement_adsh, announcement_date,
            label_30, label_90, label_180, last_close, last_close_date, price_source,
            latest_10k_date, latest_10q_date, revenue, revenue_filed, assets, assets_filed,
            cash, cash_filed, equity, equity_filed, debt, debt_filed, shares, shares_filed,
            facts_status, company_outcome, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cik, ticker, snapshot.isoformat(), kind, adsh, announcement,
         labels[30], labels[90], labels[180])
        + feature_tuple(chosen, ten_k, ten_q, figures, "stored" if fact_file else "not_retrieved")
        + (outcome, iso_now()),
    )


def feature_tuple(chosen, ten_k, ten_q, figures, facts_status):
    def pair(name):
        item = (figures or {}).get(name) or {}
        return item.get("value"), item.get("filed")
    revenue, revenue_filed = pair("revenue")
    assets, assets_filed = pair("assets")
    cash, cash_filed = pair("cash")
    equity, equity_filed = pair("equity")
    debt, debt_filed = pair("debt")
    shares, shares_filed = pair("shares")
    return (
        None if chosen is None else chosen["close"],
        None if chosen is None else chosen["date"].isoformat(),
        None if chosen is None else "yahoo-chart",
        ten_k, ten_q, revenue, revenue_filed, assets, assets_filed, cash, cash_filed,
        equity, equity_filed, debt, debt_filed, shares, shares_filed, facts_status,
    )


def latest_statement(sub, snapshot, prefix):
    if not sub:
        return None
    cutoff = snapshot.isoformat()
    dates = [item["date"] for item in sub.get("filings") or []
             if item.get("date") and item["date"] <= cutoff and (item.get("form") or "").startswith(prefix)]
    return max(dates) if dates else None


def load_bars(conn, ticker):
    if not ticker:
        return []
    rows = conn.execute(
        "SELECT bar_date, close FROM historical_stock_prices WHERE ticker=? AND source='yahoo-chart' ORDER BY bar_date",
        (ticker,),
    ).fetchall()
    return [{"date": date.fromisoformat(row["bar_date"]), "close": row["close"]} for row in rows]


def read_cached_submissions(cik):
    path = os.path.join(SUBS, "%d.json" % int(cik))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read_cached_facts(cik):
    path = os.path.join(FACTS, "%d.json" % int(cik))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def attach_event_prices(conn):
    rows = conn.execute(
        """SELECT t.adsh, t.target_ticker, t.announcement_date, t.offer_price
           FROM historical_ma_transactions t
           WHERE %s AND t.announcement_date IS NOT NULL""" % VERIFIED
    ).fetchall()
    for row in rows:
        bars = load_bars(conn, row["target_ticker"])
        if not bars:
            continue
        announcement = date.fromisoformat(row["announcement_date"])
        points = {
            "before": trading_offset(bars, announcement, -1),
            "day0": trading_offset(bars, announcement, 0),
            "day1": trading_offset(bars, announcement, 1),
            "day5": trading_offset(bars, announcement, 5),
            "day10": trading_offset(bars, announcement, 10),
            "day30": trading_offset(bars, announcement, 30),
        }
        premium = None
        if row["offer_price"] and points["before"] and points["before"]["close"]:
            premium = row["offer_price"] / points["before"]["close"] - 1
        conn.execute(
            """UPDATE historical_deal_outcomes SET
                price_before=?, price_before_date=?, price_day0=?, price_day0_date=?,
                price_day1=?, price_day1_date=?, price_day5=?, price_day5_date=?,
                price_day10=?, price_day10_date=?, price_day30=?, price_day30_date=?,
                price_source=?, observed_premium=?
               WHERE adsh=?""",
            tuple(value for point in ("before", "day0", "day1", "day5", "day10", "day30")
                  for value in ((None, None) if points[point] is None else (points[point]["close"], points[point]["date"].isoformat())))
            + ("yahoo-chart" if any(points.values()) else None, premium, row["adsh"]),
        )
    conn.commit()


def provider_notes(conn):
    notes = []
    try:
        financial_modeling_prep_bars("AAPL", date(2024, 1, 2), date(2024, 1, 5))
        notes.append("Financial Modeling Prep was called.")
    except SourceError as exc:
        notes.append(str(exc))
    try:
        polygon_bars("AAPL", date(2024, 1, 2), date(2024, 1, 5))
        notes.append("Polygon was called.")
    except SourceError as exc:
        notes.append(str(exc))
    try:
        status, body = pricemod._get("https://stooq.com/q/d/l/?s=aapl.us&d1=20240102&d2=20240105&i=d")
        state = stooq_status(body.decode("utf-8", "replace")[:800])
        notes.append("Stooq probe returned HTTP %s and was %s. No Stooq prices were stored." % (status, state))
    except SourceError as exc:
        notes.append("Stooq probe failed: %s" % exc)
    for symbol, start, end, label in (
        ("CIR", date(2023, 5, 1), date(2023, 6, 6), "CIRCOR window"),
        ("PRTK", date(2023, 5, 1), date(2023, 6, 7), "Paratek window"),
    ):
        try:
            parsed = pricemod.fetch_yahoo(symbol, start, end)
            probe = pricemod.fetch_yahoo_meta(symbol)
        except SourceError as exc:
            notes.append("%s: %s" % (label, exc))
            continue
        meta = probe.get("meta") or {}
        first = meta.get("firstTradeDate")
        first_day = datetime.fromtimestamp(int(first), tz=timezone.utc).date().isoformat() if first else "unknown"
        notes.append(
            "%s: Yahoo HTTP %s (%s). Current listing %s, first trade %s. Those recent bars were not stored as the old company's history."
            % (label, parsed.get("httpStatus"), parsed.get("error") or parsed.get("errorCode"),
               meta.get("longName") or meta.get("shortName") or "unnamed", first_day)
        )
    notes.append(
        "On a 2023 first-quarter check, EDGAR full-text pages from=0 and from=100 shared 15 of 100 accessions. "
        "Hits are deduplicated by accession. A page overlap can also skip a filing, so the search list is not a complete census."
    )
    notes.append("No historical news archive is connected. historical_news_signals was not filled.")
    notes.append("Financial statements are taken from SEC companyfacts only when the fact's filed date is on or before the snapshot.")
    for note in notes:
        conn.execute("INSERT OR REPLACE INTO provider_notes (name, detail) VALUES (?, ?)", (note[:80], note))
    conn.commit()
    return notes


def collect_stats(conn):
    def one(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]
    verified = one("SELECT COUNT(*) FROM historical_ma_transactions WHERE %s" % VERIFIED)
    missing = []
    for column in (
        "target_ticker", "acquirer_name", "acquirer_ticker", "consideration", "offer_price",
        "exchange_ratio", "transaction_value",
    ):
        missing.append((column, one(
            "SELECT COUNT(*) FROM historical_ma_transactions WHERE %s AND %s IS NULL" % (VERIFIED, column)
        )))
    missing.append(("outcome", one(
        """SELECT COUNT(*) FROM historical_ma_transactions t
           LEFT JOIN historical_deal_outcomes o ON o.adsh=t.adsh
           WHERE %s AND (o.outcome IS NULL OR o.outcome='unresolved' OR o.outcome='conflict')"""
        % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))
    )))
    usable = {}
    for days, column in ((30, "label_30"), (90, "label_90"), (180, "label_180")):
        usable[days] = one(
            """SELECT COUNT(*) FROM historical_company_snapshots
               WHERE %s IS NOT NULL
                 AND (last_close IS NOT NULL OR latest_10k_date IS NOT NULL OR revenue IS NOT NULL)
                 AND (last_close_date IS NULL OR last_close_date <= snapshot_date)
                 AND (revenue_filed IS NULL OR revenue_filed <= snapshot_date)
                 AND (latest_10k_date IS NULL OR latest_10k_date <= snapshot_date)""" % column
        )
        usable["pos%d" % days] = one(
            """SELECT COUNT(*) FROM historical_company_snapshots
               WHERE %s=1 AND (last_close IS NOT NULL OR latest_10k_date IS NOT NULL OR revenue IS NOT NULL)
                 AND (last_close_date IS NULL OR last_close_date <= snapshot_date)""" % column
        )
        usable["neg%d" % days] = one(
            """SELECT COUNT(*) FROM historical_company_snapshots
               WHERE %s=0 AND (last_close IS NOT NULL OR latest_10k_date IS NOT NULL OR revenue IS NOT NULL)
                 AND (last_close_date IS NULL OR last_close_date <= snapshot_date)""" % column
        )
    def offset(column):
        return one(
            """SELECT COUNT(*) FROM historical_deal_outcomes o
               JOIN historical_ma_transactions t ON t.adsh=o.adsh
               WHERE %s AND o.%s IS NOT NULL""" % (" AND ".join("t." + part.strip() for part in VERIFIED.split("AND")), column)
        )
    return {
        "generatedAt": iso_now(),
        "search_hits": one("SELECT COUNT(*) FROM search_hits"),
        "filings_read": one("SELECT COUNT(*) FROM search_hits WHERE text_status='read'"),
        "verified_transactions": verified,
        "buyer_filings": one("SELECT COUNT(*) FROM historical_ma_transactions WHERE role='buyer'"),
        "not_verified_roles": one("SELECT COUNT(*) FROM search_hits WHERE text_status='read' AND role IN ('unclear', 'not_merger')"),
        "competing_links": one("SELECT COUNT(*) FROM historical_ma_transactions WHERE %s AND competing_adsh IS NOT NULL" % VERIFIED),
        "closed": one("SELECT COUNT(*) FROM historical_deal_outcomes o JOIN historical_ma_transactions t ON t.adsh=o.adsh WHERE %s AND o.outcome='closed'" % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))),
        "terminated": one("SELECT COUNT(*) FROM historical_deal_outcomes o JOIN historical_ma_transactions t ON t.adsh=o.adsh WHERE %s AND o.outcome='terminated'" % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))),
        "unresolved": one("SELECT COUNT(*) FROM historical_deal_outcomes o JOIN historical_ma_transactions t ON t.adsh=o.adsh WHERE %s AND o.outcome IN ('unresolved', 'conflict')" % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))),
        "non_acquired_companies": one("SELECT COUNT(DISTINCT cik) FROM historical_company_snapshots WHERE kind='non_acquired'"),
        "tickers_with_prices": one("SELECT COUNT(DISTINCT ticker) FROM historical_stock_prices"),
        "tickers_requested": one("SELECT COUNT(DISTINCT ticker) FROM price_coverage"),
        "usable_30": usable[30], "usable_90": usable[90], "usable_180": usable[180],
        "positives_30": usable["pos30"], "positives_90": usable["pos90"], "positives_180": usable["pos180"],
        "negatives_30": usable["neg30"], "negatives_90": usable["neg90"], "negatives_180": usable["neg180"],
        "event_deals": one(
            """SELECT COUNT(*) FROM historical_deal_outcomes o
               JOIN historical_ma_transactions t ON t.adsh=o.adsh
               WHERE %s AND o.price_before IS NOT NULL AND (o.price_day0 IS NOT NULL OR o.price_day1 IS NOT NULL)"""
            % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))
        ),
        "price_before": offset("price_before"),
        "price_day0": offset("price_day0"),
        "price_day1": offset("price_day1"),
        "price_day5": offset("price_day5"),
        "price_day10": offset("price_day10"),
        "price_day30": offset("price_day30"),
        "premiums": one(
            """SELECT COUNT(*) FROM historical_deal_outcomes o
               JOIN historical_ma_transactions t ON t.adsh=o.adsh
               WHERE %s AND o.observed_premium IS NOT NULL"""
            % " AND ".join("t." + part.strip() for part in VERIFIED.split("AND"))
        ),
        "news_rows": one("SELECT COUNT(*) FROM historical_news_signals"),
        "lookahead_violations": one(
            """SELECT COUNT(*) FROM historical_company_snapshots
               WHERE (last_close_date IS NOT NULL AND last_close_date > snapshot_date)
                  OR (revenue_filed IS NOT NULL AND revenue_filed > snapshot_date)
                  OR (latest_10k_date IS NOT NULL AND latest_10k_date > snapshot_date)
                  OR (assets_filed IS NOT NULL AND assets_filed > snapshot_date)"""
        ),
        "missing_fields": missing,
        "unread_hits": one("SELECT COUNT(*) FROM search_hits WHERE text_status IS NULL AND form NOT LIKE '%/A' AND items LIKE '%1.01%'"),
        "model_file_present": os.path.exists(os.path.join(ROOT, "data", "model.json")),
        "search_short": one("SELECT COUNT(*) FROM ingest_windows WHERE note LIKE 'page union%'"),
    }


def write_report(conn, limitations):
    stats = collect_stats(conn)
    judgment = reportmod.judge(stats)
    limitations = list(limitations or [])
    limitations.append("Unread item 1.01 search hits remaining: %d." % stats["unread_hits"])
    limitations.append("Search windows whose saved hits are below the count EDGAR reported: %d." % stats.get("search_short", 0))
    limitations.append("Repeated companies are not independent observations. Distinct non-acquired companies: %d." % stats["non_acquired_companies"])
    limitations.append("A control label of zero means the three EDGAR phrases returned no hit. It does not prove the company was never acquired.")
    limitations.append("Target snapshots are dated from a known announcement. They are case-control rows, not a random draw of the market.")
    limitations.append("Production close probabilities were not changed, and no model file was written by this script.")
    text = reportmod.render_markdown(stats, judgment, limitations)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    md_path = os.path.join(ROOT, "reports", "historical_data_readiness.md")
    json_path = os.path.join(ROOT, "reports", "historical_data_readiness.json")
    payload = {"stats": stats, "judgment": judgment, "limitations": limitations}
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print("verified", stats["verified_transactions"], "read", stats["filings_read"], "usable180", stats["usable_180"])
    print("ready", {key: judgment[key] for key in ("acquisition", "post_announcement_price", "deal_completion")})
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--per-year", type=int, default=250)
    parser.add_argument("--max-filings", type=int, default=0)
    parser.add_argument("--facts-limit", type=int, default=400)
    parser.add_argument("--outcome-limit", type=int, default=0)
    parser.add_argument("--controls-per-week", type=int, default=8)
    parser.add_argument("--stage", default="all",
                        choices=["all", "search", "classify", "outcomes", "controls", "prices", "facts", "snapshots", "report"])
    args = parser.parse_args()
    ua = user_agent()
    conn = connect(DB)
    init(conn)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    stage = args.stage
    limitations = []
    try:
        if stage in ("all", "search"):
            search(conn, ua, start, end)
        if stage in ("all", "classify"):
            classify(conn, ua, args.per_year, args.max_filings)
            mark_duplicates(conn)
        if stage in ("all", "outcomes"):
            outcomes(conn, ua, args.outcome_limit)
        if stage in ("all", "controls"):
            controls(conn, ua, args.controls_per_week)
        if stage in ("all", "prices"):
            prices(conn, ua)
        if stage in ("all", "facts"):
            facts(conn, ua, args.facts_limit)
        if stage in ("all", "snapshots"):
            snapshots(conn)
            attach_event_prices(conn)
        if stage in ("all", "report", "snapshots"):
            limitations = provider_notes(conn)
    finally:
        if stage in ("all", "report", "snapshots"):
            write_report(conn, limitations)
        conn.close()


if __name__ == "__main__":
    main()
