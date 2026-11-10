"""DOC 2.0 company queries. This is not the historical ingestion path.

GDELT answers those queries with HTTP 429. Bulk GKG files are read by
scripts/build_gdelt_bulk_pilot.py. The functions below are not called from the app.

Collect GDELT DOC timelines for SEC companies and write the news reports.

The DOC API allows about one request every five seconds. Raw 15-minute GKG files
from February 2015 are not downloaded. Nothing here changes production scoring.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from historical import gdelt
from historical.labels import horizon_label
from predictive.gates import acquisition_ready
from predictive.logistic import fit, probability

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
GDELT_DB = os.path.join(ROOT, "data", "historical", "gdelt.sqlite")
SUBS = os.path.join(ROOT, "data", "historical", "submissions")
REPORTS = os.path.join(ROOT, "reports")
API = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "DealRadar local research historical news"
PAUSE_SECONDS = 12
MEASURED = (
    "A 1-20 August 2017 timelinevolraw query for \"GoPro\" returned HTTP 200, daily article counts, "
    "and the count of all articles GDELT monitored that day. All 20 days were present. "
    "A 1-8 August 2017 timelinetone query returned hourly average tone, including hours with tone 0. "
    "A 19 February 2015 timelinevolraw query returned HTTP 200 and the text \"Invalid query start date.\" "
    "The 15-minute file 20150218230000.gkg.csv.zip is 10,768,507 bytes and was not downloaded. "
    "The web-ngram file for 1 January 2017 returned HTTP 404. A 30 June 2026 ngram minute file is "
    "8,192,280 bytes and was not downloaded. Calls made close together returned HTTP 429 and no rows."
)


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    os.makedirs(os.path.dirname(GDELT_DB), exist_ok=True)
    conn = sqlite3.connect(GDELT_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS gdelt_company (
        cik INTEGER NOT NULL,
        snapshot_date TEXT NOT NULL,
        announcement_date TEXT,
        announcement_adsh TEXT NOT NULL DEFAULT '',
        kind TEXT,
        label INTEGER,
        name TEXT,
        ticker TEXT,
        phrase TEXT,
        ticker_term TEXT,
        identity_status TEXT,
        identity_reason TEXT,
        PRIMARY KEY (cik, snapshot_date, announcement_adsh)
    );
    CREATE TABLE IF NOT EXISTS gdelt_request (
        cik INTEGER NOT NULL,
        snapshot_date TEXT NOT NULL,
        announcement_adsh TEXT NOT NULL DEFAULT '',
        series TEXT NOT NULL,
        query TEXT,
        mode TEXT,
        window_start TEXT,
        window_end TEXT,
        http_status INTEGER,
        error TEXT,
        point_count INTEGER,
        retrieved_at TEXT,
        PRIMARY KEY (cik, snapshot_date, announcement_adsh, series)
    );
    CREATE TABLE IF NOT EXISTS gdelt_bucket (
        cik INTEGER NOT NULL,
        snapshot_date TEXT NOT NULL,
        announcement_adsh TEXT NOT NULL DEFAULT '',
        series TEXT NOT NULL,
        bucket_at TEXT NOT NULL,
        bucket_date TEXT NOT NULL,
        value REAL,
        norm REAL,
        PRIMARY KEY (cik, snapshot_date, announcement_adsh, series, bucket_at)
    );
    CREATE TABLE IF NOT EXISTS gdelt_article (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cik INTEGER,
        snapshot_date TEXT,
        announcement_adsh TEXT,
        url TEXT,
        title TEXT,
        seen_at TEXT,
        published_at TEXT,
        domain TEXT,
        language TEXT,
        retrieved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS gdelt_features (
        cik INTEGER NOT NULL,
        snapshot_date TEXT NOT NULL,
        announcement_adsh TEXT NOT NULL DEFAULT '',
        kind TEXT,
        label INTEGER,
        coverage TEXT,
        mentions_7 REAL,
        mentions_30 REAL,
        mentions_90 REAL,
        change_7 REAL,
        change_30 REAL,
        change_90 REAL,
        tone_7 REAL,
        tone_30 REAL,
        tone_90 REAL,
        keywords_7 REAL,
        keywords_30 REAL,
        keywords_90 REAL,
        keyword_change_30 REAL,
        PRIMARY KEY (cik, snapshot_date, announcement_adsh)
    );
    CREATE TABLE IF NOT EXISTS gdelt_notes (
        name TEXT PRIMARY KEY,
        detail TEXT
    );
    """)
    return conn


def submission_name(cik):
    path = os.path.join(SUBS, "%d.json" % int(cik))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("name")


def load_companies(limit):
    sec = sqlite3.connect(SEC_DB)
    sec.row_factory = sqlite3.Row
    today = date.today()
    backed = {
        (row["cik"], row["snapshot_date"], row["kind"])
        for row in sec.execute(
            """SELECT cik, snapshot_date, kind FROM historical_company_snapshots
               WHERE last_close IS NOT NULL OR revenue IS NOT NULL OR assets IS NOT NULL"""
        )
    }
    companies = []
    controls = sec.execute(
        """SELECT cik, ticker, snapshot_date, label_30 FROM historical_company_snapshots
           WHERE kind='non_acquired' AND snapshot_date IS NOT NULL"""
    ).fetchall()
    for row in controls:
        snapshot = date.fromisoformat(row["snapshot_date"])
        companies.append({
            "cik": row["cik"],
            "snapshot": snapshot,
            "announcement": None,
            "adsh": "",
            "kind": "non_acquired",
            "label": row["label_30"],
            "name": submission_name(row["cik"]),
            "ticker": row["ticker"],
        })
        if (row["cik"], row["snapshot_date"], "non_acquired") not in backed:
            companies[-1]["sec_ready"] = False
        else:
            companies[-1]["sec_ready"] = True
    deals = sec.execute(
        """SELECT adsh, target_cik, target_name, target_ticker, announcement_date
           FROM historical_ma_transactions
           WHERE role='target' AND is_amendment=0 AND duplicate_of IS NULL
             AND announcement_date IS NOT NULL AND target_cik IS NOT NULL
           ORDER BY announcement_date, adsh"""
    ).fetchall()
    by_year = {}
    for row in deals:
        announcement = date.fromisoformat(row["announcement_date"])
        snapshot = announcement - timedelta(days=30)
        if snapshot < gdelt.DOC_COVERAGE_START:
            continue
        label = horizon_label(snapshot, announcement, 30, today)
        item = {
            "cik": row["target_cik"],
            "snapshot": snapshot,
            "announcement": announcement,
            "adsh": row["adsh"],
            "kind": "target",
            "label": label,
            "name": row["target_name"] or submission_name(row["target_cik"]),
            "ticker": row["target_ticker"],
            "sec_ready": (row["target_cik"], snapshot.isoformat(), "target_pre") in backed,
        }
        by_year.setdefault(announcement.year, []).append(item)
    controls = [row for row in companies if row["label"] is not None and row.get("sec_ready")]
    years = sorted(by_year)
    targets = []
    if years:
        cursors = {year: 0 for year in years}
        while True:
            added = False
            for year in years:
                group = [item for item in by_year[year] if item["label"] is not None and item.get("sec_ready")]
                index = cursors[year]
                if index < len(group):
                    targets.append(group[index])
                    cursors[year] += 1
                    added = True
            if not added:
                break
    if limit is None:
        sec.close()
        return controls + targets
    control_cap = max(1, limit // 3)
    chosen_controls = controls[:control_cap]
    chosen_targets = targets[:max(0, limit - len(chosen_controls))]
    sec.close()
    return chosen_controls + chosen_targets


def store_companies(conn, companies):
    for row in companies:
        found = gdelt.identity(row["name"], row["ticker"])
        conn.execute(
            """INSERT INTO gdelt_company (
                cik, snapshot_date, announcement_date, announcement_adsh, kind, label,
                name, ticker, phrase, ticker_term, identity_status, identity_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, snapshot_date, announcement_adsh) DO UPDATE SET
                name=excluded.name, ticker=excluded.ticker, phrase=excluded.phrase,
                ticker_term=excluded.ticker_term, identity_status=excluded.identity_status,
                identity_reason=excluded.identity_reason, label=excluded.label, kind=excluded.kind
            """,
            (row["cik"], row["snapshot"].isoformat(),
             None if row["announcement"] is None else row["announcement"].isoformat(),
             row["adsh"], row["kind"], row["label"], row["name"], row["ticker"],
             found["phrase"], found["ticker_term"], found["status"], found["reason"]),
        )
    conn.commit()


def fetch(params):
    quoted = "&".join("%s=%s" % (key, _url(value)) for key, value in params.items())
    url = API + "?" + quoted
    completed = subprocess.run(
        ["curl", "-sS", "-m", "70", "-A", USER_AGENT, "-w", "\n%{http_code}", url],
        capture_output=True, text=True,
    )
    output = completed.stdout or ""
    if "\n" not in output:
        return 0, output, completed.stderr
    body, status = output.rsplit("\n", 1)
    try:
        code = int(status.strip())
    except ValueError:
        code = 0
    return code, body, completed.stderr


def _url(value):
    from urllib.parse import quote
    return quote(str(value), safe="")


def already_requested(conn, row, series):
    found = conn.execute(
        """SELECT http_status FROM gdelt_request
           WHERE cik=? AND snapshot_date=? AND announcement_adsh=? AND series=?""",
        (row["cik"], row["snapshot_date"], row["announcement_adsh"], series),
    ).fetchone()
    return found is not None and found["http_status"] == 200


def request_series(conn, row, series, mode, query, start, end):
    if already_requested(conn, row, series):
        return "cached"
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "STARTDATETIME": start.strftime("%Y%m%d") + "000000",
        "ENDDATETIME": (end + timedelta(days=1)).strftime("%Y%m%d") + "000000",
    }
    code, body, error = fetch(params)
    attempt = 0
    while code == 429 and attempt < 2:
        attempt += 1
        time.sleep(20)
        code, body, error = fetch(params)
    point_count = 0
    message = None
    if code == 200:
        try:
            points = gdelt.parse_timeline(json.loads(body))
        except (ValueError, json.JSONDecodeError) as exc:
            code = 0
            message = str(exc)
            points = []
        else:
            kept = gdelt.on_or_before(points, date.fromisoformat(row["snapshot_date"]))
            point_count = len(kept)
            conn.execute(
                """DELETE FROM gdelt_bucket
                   WHERE cik=? AND snapshot_date=? AND announcement_adsh=? AND series=?""",
                (row["cik"], row["snapshot_date"], row["announcement_adsh"], series),
            )
            conn.executemany(
                """INSERT INTO gdelt_bucket (
                    cik, snapshot_date, announcement_adsh, series, bucket_at, bucket_date, value, norm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(row["cik"], row["snapshot_date"], row["announcement_adsh"], series,
                  point["bucket_at"], point["bucket_date"].isoformat(), point["value"], point["norm"])
                 for point in kept],
            )
    else:
        message = (body or error or "")[:300].replace("\n", " ")
    conn.execute(
        """INSERT INTO gdelt_request (
            cik, snapshot_date, announcement_adsh, series, query, mode, window_start, window_end,
            http_status, error, point_count, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik, snapshot_date, announcement_adsh, series) DO UPDATE SET
            query=excluded.query, mode=excluded.mode, window_start=excluded.window_start,
            window_end=excluded.window_end, http_status=excluded.http_status, error=excluded.error,
            point_count=excluded.point_count, retrieved_at=excluded.retrieved_at
        """,
        (row["cik"], row["snapshot_date"], row["announcement_adsh"], series, query, mode,
         start.isoformat(), end.isoformat(), code, message, point_count, iso_now()),
    )
    conn.commit()
    if code == 429:
        return "blocked"
    return "ok" if code == 200 else "failed"


def collect(conn, pause, max_calls):
    rows = conn.execute(
        """SELECT * FROM gdelt_company WHERE identity_status='queryable' AND label IS NOT NULL
           ORDER BY CASE WHEN kind='non_acquired' THEN 0 ELSE 1 END, snapshot_date"""
    ).fetchall()
    consecutive_blocks = 0
    calls = 0
    for row in rows:
        snapshot = date.fromisoformat(row["snapshot_date"])
        if snapshot < gdelt.DOC_COVERAGE_START:
            continue
        start = max(gdelt.DOC_COVERAGE_START, snapshot - timedelta(days=179))
        query = gdelt.mention_query(row["phrase"], row["ticker_term"])
        keywords = gdelt.keyword_query(row["phrase"], row["ticker_term"])
        series_calls = (
            ("mentions", "timelinevolraw", query),
            ("tone", "timelinetone", query),
            ("keywords", "timelinevolraw", keywords),
        )
        for series, mode, text in series_calls:
            if already_requested(conn, row, series):
                continue
            if max_calls is not None and calls >= max_calls:
                return
            calls += 1
            status = request_series(conn, row, series, mode, text, start, snapshot)
            print(row["snapshot_date"], row["phrase"], series, status, flush=True)
            if status == "blocked":
                consecutive_blocks += 1
                if consecutive_blocks >= 3:
                    return
                time.sleep(45)
                continue
            consecutive_blocks = 0
            if status != "cached":
                time.sleep(pause)


def _points(conn, row, series):
    found = conn.execute(
        """SELECT bucket_date, bucket_at, value FROM gdelt_bucket
           WHERE cik=? AND snapshot_date=? AND announcement_adsh=? AND series=?""",
        (row["cik"], row["snapshot_date"], row["announcement_adsh"], series),
    ).fetchall()
    return [{"bucket_date": date.fromisoformat(item["bucket_date"]), "bucket_at": item["bucket_at"],
             "value": item["value"]} for item in found]


def features(conn):
    conn.execute("DELETE FROM gdelt_features")
    rows = conn.execute("SELECT * FROM gdelt_company").fetchall()
    for row in rows:
        requests = {
            item["series"]: item for item in conn.execute(
                """SELECT series, http_status FROM gdelt_request
                   WHERE cik=? AND snapshot_date=? AND announcement_adsh=?""",
                (row["cik"], row["snapshot_date"], row["announcement_adsh"]),
            )
        }
        snapshot = date.fromisoformat(row["snapshot_date"])
        if row["identity_status"] != "queryable":
            coverage = row["identity_status"]
        elif snapshot < gdelt.DOC_COVERAGE_START:
            coverage = "before_doc_coverage"
        elif row["label"] is None:
            coverage = "censored"
        elif any(requests.get(name, {"http_status": None})["http_status"] != 200 for name in ("mentions", "tone", "keywords")):
            coverage = "not_retrieved" if not requests else "request_failed"
        else:
            coverage = "retrieved"
        values = {}
        if coverage == "retrieved":
            built = gdelt.feature_row(_points(conn, row, "mentions"), _points(conn, row, "tone"),
                                      _points(conn, row, "keywords"), snapshot)
            values = built
            coverage = "observed" if built["mentions_30"] is not None and built["keywords_30"] is not None else "incomplete"
        conn.execute(
            """INSERT INTO gdelt_features (
                cik, snapshot_date, announcement_adsh, kind, label, coverage,
                mentions_7, mentions_30, mentions_90, change_7, change_30, change_90,
                tone_7, tone_30, tone_90, keywords_7, keywords_30, keywords_90, keyword_change_30
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["cik"], row["snapshot_date"], row["announcement_adsh"], row["kind"], row["label"], coverage,
             values.get("mentions_7"), values.get("mentions_30"), values.get("mentions_90"),
             values.get("change_7"), values.get("change_30"), values.get("change_90"),
             values.get("tone_7"), values.get("tone_30"), values.get("tone_90"),
             values.get("keywords_7"), values.get("keywords_30"), values.get("keywords_90"),
             values.get("keyword_change_30")),
        )
    conn.commit()


def sec_features(ciks_and_dates):
    """Point-in-time SEC fields already stored on the snapshot. No new filings are read."""
    if not os.path.exists(SEC_DB):
        return {}
    sec = sqlite3.connect(SEC_DB)
    sec.row_factory = sqlite3.Row
    found = {}
    for cik, snapshot, kind in ciks_and_dates:
        if kind == "target":
            row = sec.execute(
                """SELECT last_close, revenue, assets, cash, debt
                   FROM historical_company_snapshots
                   WHERE cik=? AND snapshot_date=? AND kind='target_pre'
                   ORDER BY id LIMIT 1""",
                (cik, snapshot),
            ).fetchone()
        else:
            row = sec.execute(
                """SELECT last_close, revenue, assets, cash, debt
                   FROM historical_company_snapshots
                   WHERE cik=? AND snapshot_date=? AND kind='non_acquired'
                   ORDER BY id LIMIT 1""",
                (cik, snapshot),
            ).fetchone()
        found[(cik, snapshot, kind)] = None if row is None else dict(row)
    sec.close()
    return found


def _scale(value):
    if value is None or value < 0:
        return None
    import math
    return math.log1p(value)


def comparison_rows(conn):
    news_rows = conn.execute(
        """SELECT * FROM gdelt_features WHERE coverage='observed' AND label IS NOT NULL"""
    ).fetchall()
    keys = [(row["cik"], row["snapshot_date"], "target" if row["kind"] == "target" else "non_acquired")
            for row in news_rows]
    sec = sec_features(keys)
    paired = []
    for row in news_rows:
        kind = "target" if row["kind"] == "target" else "non_acquired"
        base = sec.get((row["cik"], row["snapshot_date"], kind))
        if not base:
            continue
        has_market = base["last_close"] is not None
        has_statement = base["revenue"] is not None or base["assets"] is not None
        if not has_market and not has_statement:
            continue
        assets = base["assets"] if base["assets"] not in (None, 0) else None
        paired.append({
            "snapshot": row["snapshot_date"],
            "label": int(row["label"]),
            "sec": [
                _scale(base["last_close"]),
                None if assets is None or base["cash"] is None else base["cash"] / assets,
                None if assets is None or base["debt"] is None else base["debt"] / assets,
                None if assets is None or base["revenue"] is None else base["revenue"] / assets,
                _scale(base["assets"]),
            ],
            "news": [
                _scale(row["mentions_30"]),
                row["change_30"],
                row["tone_30"],
                _scale(row["keywords_30"]),
                row["keyword_change_30"],
            ],
        })
    return paired


def _impute(train, test):
    width = len(train[0]) if train else 0
    medians = []
    for index in range(width):
        present = sorted(row[index] for row in train if row[index] is not None)
        medians.append(present[len(present) // 2] if present else 0.0)
    def fill(rows):
        filled = []
        flags = []
        for row in rows:
            values = []
            missing = []
            for index, value in enumerate(row):
                missing.append(1.0 if value is None else 0.0)
                values.append(medians[index] if value is None else value)
            filled.append(values + missing)
            flags.append(missing)
        return filled
    return fill(train), fill(test)


def _evaluate(labels, scores, threshold):
    return {
        "pr_auc": gdelt.average_precision(labels, scores),
        "brier": gdelt.brier(labels, scores),
        "classification": gdelt.classification(labels, scores, threshold),
        "calibration": gdelt.calibration(labels, scores),
        "n": len(labels),
        "positives": sum(labels),
    }


def compare(rows):
    """Fit only when the paired sample clears the existing acquisition gate.

    The returned scores are research measurements. They are not saved as a model.
    """
    counts = {
        "rows": len(rows),
        "positives": sum(row["label"] for row in rows),
        "negatives": sum(1 for row in rows if row["label"] == 0),
    }
    ordered = sorted(rows, key=lambda row: row["snapshot"])
    split = int(len(ordered) * 0.7)
    train, test = ordered[:split], ordered[split:]
    counts["holdout"] = len(test)
    ready, missing = acquisition_ready(counts)
    if not ready or not train or not test:
        return {"ready": False, "missing": missing, "counts": counts, "arms": None}
    if sum(row["label"] for row in train) in (0, len(train)) or sum(row["label"] for row in test) in (0, len(test)):
        return {"ready": False, "missing": ["both classes in the train and test periods"], "counts": counts, "arms": None}
    threshold = sum(row["label"] for row in train) / len(train)
    arms = {}
    specs = {
        "sec": lambda row: row["sec"],
        "news": lambda row: row["news"],
        "both": lambda row: row["sec"] + row["news"],
    }
    test_labels = [row["label"] for row in test]
    constant = [threshold] * len(test)
    arms["constant"] = _evaluate(test_labels, constant, threshold)
    for name, getter in specs.items():
        train_raw = [getter(row) for row in train]
        test_raw = [getter(row) for row in test]
        train_x, test_x = _impute(train_raw, test_raw)
        weights = fit(train_x, [row["label"] for row in train], steps=500, learning_rate=0.15)
        scores = [probability(weights, row) for row in test_x]
        arms[name] = _evaluate(test_labels, scores, threshold)
    return {"ready": True, "missing": [], "counts": counts, "arms": arms, "threshold": threshold,
            "train_end": train[-1]["snapshot"], "test_start": test[0]["snapshot"]}


def _count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def write_reports(conn, result, probe):
    os.makedirs(REPORTS, exist_ok=True)
    companies = _count(conn, "SELECT COUNT(*) FROM gdelt_company")
    by_status = conn.execute(
        "SELECT identity_status, COUNT(*) n FROM gdelt_company GROUP BY 1 ORDER BY 1"
    ).fetchall()
    by_coverage = conn.execute(
        "SELECT coverage, kind, label, COUNT(*) n FROM gdelt_features GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
    ).fetchall()
    requests = conn.execute(
        "SELECT series, http_status, COUNT(*) n FROM gdelt_request GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    observed = _count(conn, "SELECT COUNT(*) FROM gdelt_features WHERE coverage='observed'")
    zeros = _count(conn, "SELECT COUNT(*) FROM gdelt_features WHERE coverage='observed' AND mentions_30=0")
    future = _count(conn, """SELECT COUNT(*) FROM gdelt_bucket b
        JOIN gdelt_company c ON c.cik=b.cik AND c.snapshot_date=b.snapshot_date
         AND c.announcement_adsh=b.announcement_adsh
        WHERE b.bucket_date > c.snapshot_date""")
    articles = _count(conn, "SELECT COUNT(*) FROM gdelt_article")
    published = _count(conn, "SELECT COUNT(*) FROM gdelt_article WHERE published_at IS NOT NULL")
    feature_nulls = {}
    for column in ("mentions_7", "mentions_30", "mentions_90", "change_7", "change_30", "change_90",
                   "tone_30", "keywords_30", "keyword_change_30"):
        feature_nulls[column] = (
            _count(conn, "SELECT COUNT(*) FROM gdelt_features WHERE %s IS NULL" % column),
            _count(conn, "SELECT COUNT(*) FROM gdelt_features WHERE %s IS NOT NULL" % column),
        )
    examples = conn.execute(
        """SELECT c.name, c.ticker, c.snapshot_date, c.kind, f.coverage, f.mentions_30, f.change_30,
                  f.tone_30, f.keywords_30
           FROM gdelt_features f JOIN gdelt_company c
             ON c.cik=f.cik AND c.snapshot_date=f.snapshot_date AND c.announcement_adsh=f.announcement_adsh
           WHERE f.coverage='observed'
           ORDER BY f.mentions_30 DESC LIMIT 8"""
    ).fetchall()
    readiness = _readiness(companies, by_status, by_coverage, requests, observed, zeros, future, articles, published, probe)
    feature_report = _feature_report(feature_nulls, examples, observed, zeros)
    model_report = _model_report(result)
    for name, text in (
        ("gdelt_data_readiness.md", readiness),
        ("gdelt_feature_report.md", feature_report),
        ("news_model_comparison.md", model_report),
    ):
        with open(os.path.join(REPORTS, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    print("reports written", observed, "observed rows")


def _lines(rows, keys):
    if not rows:
        return "- None.\n"
    return "".join("- " + ", ".join("%s=%s" % (key, row[key]) for key in keys) + "\n" for row in rows)


def _readiness(companies, by_status, by_coverage, requests, observed, zeros, future, articles, published, probe):
    return """# GDELT data readiness

Checked %s. No production score was changed. No probability was written into DealRadar.

## What can be retrieved

GDELT's DOC 2.0 API is the historical search that this machine can call without a subscription. Its documented full-text window now starts on 1 January 2017. Timeline volume, raw article counts, and average tone accept a start and end inside that window. The API asks for one request every five seconds. A burst is answered with HTTP 429 and no data.

The calls used here are `timelinevolraw` for mention counts, `timelinetone` for average tone, and `timelinevolraw` again for a fixed acquisition-keyword query. English-language coverage only (`sourcelang:english`). Each query is the cleaned SEC name, plus a ticker of at least three letters when that ticker is not a common word. A one-word generic name is not queried.

February 2015 through December 2016 is the start of the GDELT 2.0 15-minute files, not of this API. Those files were not downloaded. The disk had about 350MB free, and the 15-minute archive is hundreds of thousands of files. The June 2026 web-ngram feed is a current minute-by-minute histogram, not a backfile to 2015. It was not used as historical news.

Probe notes: %s

## What was stored

Companies considered: %d.

Identity:
%s
Requests:
%s
Feature coverage:
%s
Rows with a complete 30-day mention count: %d. Of those, explicit zeros: %d. A company that was not queried, a failed request, and a day the timeline did not return are missing. They are not coded as zero.

Timeline buckets dated after the prediction snapshot and still stored: %d. Features ignore any such bucket.

Article rows stored: %d. Rows with a publisher timestamp distinct from GDELT's observation time: %d. The timeline buckets are GDELT's observation time. The DOC article list's `seendate` is also an observation time. This pull did not receive a separate publication timestamp, so none was invented.

## Join

News rows carry the SEC CIK and the prediction date. Targets use the date 30 days before the announcement. Non-acquired companies use the snapshot already stored in the SEC table. The label is whether an announcement falls in the next 30 days. A horizon that has not ended is left blank. Companies with no SEC price and no SEC statement on that date were not sent to GDELT.

The SEC filing text, offer, and the announcement itself are not news features.

## Improvement

A complete mention history was observed for %d company-dates. Whether that changes a forecast is in `reports/news_model_comparison.md`. Coverage this small, or a sample that fails the existing size gate, is not evidence that news predicts acquisitions.
""" % (
        iso_now(),
        probe or "No extra archive probe was recorded.",
        companies,
        _lines(by_status, ("identity_status", "n")),
        _lines(requests, ("series", "http_status", "n")),
        _lines(by_coverage, ("coverage", "kind", "label", "n")),
        observed, zeros, future, articles, published, observed,
    )


def _feature_report(feature_nulls, examples, observed, zeros):
    null_lines = "".join(
        "- %s: %d missing, %d present\n" % (name, missing, present)
        for name, (missing, present) in feature_nulls.items()
    )
    example_lines = _lines(examples, ("name", "ticker", "snapshot_date", "kind", "coverage",
                                      "mentions_30", "change_30", "tone_30", "keywords_30"))
    return """# GDELT feature report

These features are computed only from GDELT buckets on or before the prediction date.

## Definitions

- `mentions_7`, `mentions_30`, `mentions_90`: sum of daily article counts. A day the timeline did not return makes the sum missing.
- `change_7`, `change_30`, `change_90`: the recent sum minus the sum of the immediately previous window of the same length. The 30-day change needs 60 observed days.
- `tone_7`, `tone_30`, `tone_90`: mean of the daily average tones GDELT returned. A day without a tone is skipped. If every day in the window lacks a tone, the mean is missing. Tone is not filled with zero.
- `keywords_30` and `keyword_change_30`: the same sums for articles matching the company and one fixed keyword clause: strategic review, strategic alternatives, potential sale, activist investor, takeover interest, merger rumor, acquisition, merger, or takeover.
- The separate themes were not given separate API calls. One extra call per theme would have multiplied the request count. The keyword feature is the combined count, not five independent frequencies.

Observed 30-day mention rows: %d. Explicit zeros among them: %d.

## Missing and present

%s
## Highest observed 30-day mention counts

%s
A high count is not a finding that the company was about to be acquired. Common names and large companies generate coverage for other reasons. The query string is stored on each request so a match can be checked.
""" % (observed, zeros, null_lines, example_lines)


def _fmt(value):
    if value is None:
        return "undefined"
    if isinstance(value, float):
        return "%.4f" % value
    return str(value)


def _model_report(result):
    counts = result["counts"]
    header = """# News model comparison

Prediction date: 30 days before a verified SEC announcement, or the stored snapshot for a non-acquired company. The label is an announcement inside the next 30 days. Training uses the earlier snapshots. The test uses the later snapshots. The split is chronological, not random.

The sample is the companies whose GDELT 30-day mention count was fully observed and that already have a SEC price or a SEC statement on that date. It is a case-control extract of the existing SEC file, not a draw of every public company.

Rows: %d. Positives: %d. Negatives: %d. Holdout: %d.

""" % (counts.get("rows", 0), counts.get("positives", 0), counts.get("negatives", 0), counts.get("holdout", 0))
    if not result["ready"]:
        missing = ", ".join(result["missing"]) if result["missing"] else "the sample"
        return header + """## Result

The comparison was not scored. The paired sample does not clear the existing acquisition gate (%s). No logistic model was fit. No probability was saved. News features are not an improvement over the SEC fields, because that comparison was not run.

The gate is 100 rows, 20 positives, 20 negatives, and 15 holdout rows, with both classes on each side of the date split. Lowering it would not make this sample evidence.
""" % missing
    arms = result["arms"]
    lines = ["## Result", "",
             "Train snapshots end %s. Test snapshots start %s. Decision threshold is the training positive rate, %.4f."
             % (result["train_end"], result["test_start"], result["threshold"]),
             "",
             "Missing inputs inside a row use the training median, and the model also sees a missingness flag. The median is not a news measurement.",
             "",
             "| Arm | PR-AUC | Precision | Recall | Brier | Test rows |",
             "|---|---:|---:|---:|---:|---:|"]
    order = (("Constant training rate", "constant"), ("A. SEC features only", "sec"),
             ("B. News features only", "news"), ("C. SEC plus news", "both"))
    for label, key in order:
        arm = arms[key]
        klass = arm["classification"]
        lines.append("| %s | %s | %s | %s | %s | %d |" % (
            label, _fmt(arm["pr_auc"]), _fmt(klass["precision"]), _fmt(klass["recall"]),
            _fmt(arm["brier"]), arm["n"]))
    lines.append("")
    sec_brier = arms["sec"]["brier"]
    both_brier = arms["both"]["brier"]
    news_auc = arms["news"]["pr_auc"]
    sec_auc = arms["sec"]["pr_auc"]
    both_auc = arms["both"]["pr_auc"]
    improved = both_brier is not None and sec_brier is not None and both_brier < sec_brier and both_auc is not None and sec_auc is not None and both_auc > sec_auc
    if improved:
        lines.append("On this holdout, SEC plus news has a lower Brier score and a higher PR-AUC than SEC features alone. That is a difference on this case-control sample. It is not a production probability.")
    else:
        lines.append("On this holdout, SEC plus news does not beat SEC features on both Brier score and PR-AUC. News is not treated as an improvement. News-only PR-AUC is %s against SEC-only %s." % (_fmt(news_auc), _fmt(sec_auc)))
    lines.append("")
    lines.append("## Calibration")
    lines.append("")
    for label, key in order:
        rows = arms[key]["calibration"]
        lines.append("### %s" % label)
        lines.append("")
        if not rows:
            lines.append("The holdout is too small for five calibration bins.")
            lines.append("")
            continue
        lines.append("| Bin size | Mean predicted | Observed rate |")
        lines.append("|---:|---:|---:|")
        for row in rows:
            lines.append("| %d | %.4f | %.4f |" % (row["n"], row["mean_predicted"], row["observed_rate"]))
        lines.append("")
    lines.append("These scores were not written to `data/model.json` and are not shown in the app.")
    lines.append("")
    return header + "\n".join(lines)


def main():
    limit = None
    pause = PAUSE_SECONDS
    probe = None
    max_calls = None
    args = sys.argv[1:]
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--pause" in args:
        pause = float(args[args.index("--pause") + 1])
    if "--max-calls" in args:
        max_calls = int(args[args.index("--max-calls") + 1])
    if "--probe" in args:
        probe = args[args.index("--probe") + 1]
    else:
        probe = MEASURED
    conn = connect()
    companies = load_companies(limit)
    store_companies(conn, companies)
    if "--reports-only" not in args:
        collect(conn, pause, max_calls)
    features(conn)
    result = compare(comparison_rows(conn))
    write_reports(conn, result, probe)
    conn.close()


if __name__ == "__main__":
    main()
