"""Download one day of GDELT GKG files and join them to a small SEC company set.

The DOC search API is not called. A failed file stays missing coverage.
Nothing here changes production scoring or saves a model.
"""
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from historical.gdelt_bulk import (
    backoff_seconds,
    day_complete,
    file_md5,
    gkg_files_for_day,
    https_url,
    join_day,
    match_terms,
    matching_org,
    parse_gkg_line,
    parse_index_line,
    rolling_change,
    should_retry,
    verified,
)
from historical.labels import horizon_label
from predictive.gates import acquisition_ready

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
BULK = os.path.join(ROOT, "data", "historical", "gdelt_bulk")
RAW = os.path.join(BULK, "raw")
INDEX = os.path.join(BULK, "index-20210203-gkg.txt")
MANIFEST = os.path.join(BULK, "manifest.sqlite")
PILOT = os.path.join(BULK, "pilot.sqlite")
SUBS = os.path.join(ROOT, "data", "historical", "submissions")
REPORTS = os.path.join(ROOT, "reports")
ARCHIVE_DAY = date(2021, 2, 3)
USER_AGENT = "DealRadar local research gdelt bulk pilot"


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def submission_name(cik):
    path = os.path.join(SUBS, "%d.json" % int(cik))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("name")


def load_index():
    rows = [parse_index_line(line) for line in open(INDEX, encoding="utf-8") if line.strip()]
    return gkg_files_for_day(rows, ARCHIVE_DAY)


def select_companies():
    sec = sqlite3.connect(SEC_DB)
    sec.row_factory = sqlite3.Row
    today = date.today()
    chosen = []

    def add(row):
        found, terms = match_terms(row["name"], row["ticker"], row["cik"])
        if found["status"] != "queryable" or not terms:
            return
        item = dict(row)
        item["phrase"] = found["phrase"]
        item["terms"] = terms
        item["identity"] = found["status"]
        chosen.append(item)

    controls = sec.execute(
        """SELECT cik, ticker, snapshot_date, label_30 FROM historical_company_snapshots
           WHERE kind='non_acquired' AND snapshot_date BETWEEN '2021-02-01' AND '2021-02-10'
           ORDER BY snapshot_date, cik"""
    ).fetchall()
    before_controls = 0
    window_controls = 0
    for row in controls:
        snapshot = date.fromisoformat(row["snapshot_date"])
        item = {
            "cik": row["cik"], "ticker": row["ticker"], "name": submission_name(row["cik"]),
            "snapshot": snapshot, "announcement": None, "adsh": "", "kind": "non_acquired",
            "label": row["label_30"], "group": "before_cutoff" if snapshot < ARCHIVE_DAY else "in_window",
        }
        if item["group"] == "before_cutoff" and before_controls >= 2:
            continue
        if item["group"] == "in_window" and window_controls >= 8:
            continue
        before = len(chosen)
        add(item)
        if len(chosen) > before:
            if item["group"] == "before_cutoff":
                before_controls += 1
            else:
                window_controls += 1

    deals = sec.execute(
        """SELECT adsh, target_cik, target_name, target_ticker, announcement_date
           FROM historical_ma_transactions
           WHERE role='target' AND is_amendment=0 AND duplicate_of IS NULL
             AND announcement_date>='2021-02-15' AND announcement_date<'2021-05-01'
             AND target_name NOT LIKE '%Acquisition Corp%'
             AND target_name NOT LIKE '%Acquisition Co%'
           ORDER BY announcement_date, adsh"""
    ).fetchall()
    before_targets = 0
    window_targets = 0
    for row in deals:
        announcement = date.fromisoformat(row["announcement_date"])
        snapshot = announcement - timedelta(days=30)
        item = {
            "cik": row["target_cik"], "ticker": row["target_ticker"], "name": row["target_name"],
            "snapshot": snapshot, "announcement": announcement, "adsh": row["adsh"], "kind": "target",
            "label": horizon_label(snapshot, announcement, 30, today),
            "group": "before_cutoff" if snapshot < ARCHIVE_DAY else "in_window",
        }
        if item["group"] == "before_cutoff" and before_targets >= 2:
            continue
        if item["group"] == "in_window" and window_targets >= 8:
            continue
        before = len(chosen)
        add(item)
        if len(chosen) > before:
            if item["group"] == "before_cutoff":
                before_targets += 1
            else:
                window_targets += 1
    sec.close()
    return chosen


def manifest():
    os.makedirs(RAW, exist_ok=True)
    conn = sqlite3.connect(MANIFEST)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS files (
            name TEXT PRIMARY KEY,
            url TEXT,
            expected_size INTEGER,
            expected_md5 TEXT,
            http_status INTEGER,
            retry_after TEXT,
            attempts INTEGER,
            status TEXT,
            detail TEXT,
            observed_md5 TEXT,
            recorded_at TEXT
        )"""
    )
    return conn


def curl_once(url, dest):
    header_path = dest + ".headers"
    completed = subprocess.run(
        ["curl", "-sS", "-L", "--max-redirs", "3", "-m", "120", "-A", USER_AGENT,
         "-D", header_path, "-o", dest, "-w", "%{http_code}", url],
        capture_output=True, text=True,
    )
    retry_after = None
    if os.path.exists(header_path):
        with open(header_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("retry-after:"):
                    retry_after = line.split(":", 1)[1].strip()
        os.remove(header_path)
    text = (completed.stdout or "").strip()
    try:
        status = int(text)
    except ValueError:
        status = None
    error = (completed.stderr or "").strip()[:300] or None
    if completed.returncode != 0 and status is None:
        return None, retry_after, error
    return status, retry_after, error


def download_all(files, conn):
    for row in files:
        dest = os.path.join(RAW, row["name"])
        if os.path.exists(dest) and verified(dest, row["size"], row["md5"]):
            record(conn, row, 200, None, 0, "verified", "cached", file_md5(dest))
            print(row["name"], "cached", flush=True)
            continue
        part = dest + ".part"
        attempt = 0
        status = None
        retry_after = None
        detail = None
        while True:
            status, retry_after, detail = curl_once(https_url(row["url"]), part)
            if status == 200 and verified(part, row["size"], row["md5"]):
                os.replace(part, dest)
                record(conn, row, 200, retry_after, attempt + 1, "verified", None, row["md5"])
                print(row["name"], "verified", flush=True)
                break
            if os.path.exists(part):
                os.remove(part)
            if status == 200:
                detail = "The file size or checksum did not match the archive index."
                status = 0
            if not should_retry(status, attempt):
                record(conn, row, status, retry_after, attempt + 1, "failed", detail, None)
                print(row["name"], "failed", status, flush=True)
                break
            time.sleep(backoff_seconds(attempt, random.random()))
            attempt += 1


def record(conn, row, status, retry_after, attempts, state, detail, observed):
    conn.execute(
        """INSERT INTO files (
            name, url, expected_size, expected_md5, http_status, retry_after, attempts,
            status, detail, observed_md5, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            http_status=excluded.http_status, retry_after=excluded.retry_after,
            attempts=excluded.attempts, status=excluded.status, detail=excluded.detail,
            observed_md5=excluded.observed_md5, recorded_at=excluded.recorded_at
        """,
        (row["name"], https_url(row["url"]), row["size"], row["md5"], status, retry_after,
         attempts, state, detail, observed, iso_now()),
    )
    conn.commit()


def pilot_db():
    conn = sqlite3.connect(PILOT)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS companies (
            cik INTEGER,
            snapshot_date TEXT,
            announcement_date TEXT,
            adsh TEXT,
            kind TEXT,
            label INTEGER,
            cohort TEXT,
            name TEXT,
            ticker TEXT,
            phrase TEXT,
            terms TEXT,
            PRIMARY KEY (cik, snapshot_date, adsh)
        );
        CREATE TABLE IF NOT EXISTS mentions (
            cik INTEGER,
            snapshot_date TEXT,
            adsh TEXT,
            url TEXT,
            observed_at TEXT,
            source TEXT,
            tone REAL,
            acquisition_themes TEXT,
            matched_org TEXT,
            matched_kind TEXT,
            matched_term TEXT,
            file_name TEXT,
            published_at TEXT,
            PRIMARY KEY (cik, snapshot_date, adsh, url)
        );
        CREATE TABLE IF NOT EXISTS features (
            cik INTEGER,
            snapshot_date TEXT,
            adsh TEXT,
            mentions INTEGER,
            sources INTEGER,
            tone REAL,
            acquisition_mentions INTEGER,
            change_7 REAL,
            change_30 REAL,
            change_90 REAL,
            reason TEXT,
            discarded_after_cutoff INTEGER,
            PRIMARY KEY (cik, snapshot_date, adsh)
        );
        CREATE TABLE IF NOT EXISTS parse_notes (
            name TEXT PRIMARY KEY,
            detail TEXT
        );
        """
    )
    return conn


def store_companies(conn, companies):
    conn.execute("DELETE FROM companies")
    for row in companies:
        conn.execute(
            """INSERT INTO companies (
                cik, snapshot_date, announcement_date, adsh, kind, label, cohort, name, ticker, phrase, terms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["cik"], row["snapshot"].isoformat(),
             None if row["announcement"] is None else row["announcement"].isoformat(),
             row["adsh"], row["kind"], row["label"], row["group"], row["name"], row["ticker"],
             row["phrase"], json.dumps(row["terms"])),
        )
    conn.commit()


def parse_verified(files, companies, manifest_conn, conn):
    conn.execute("DELETE FROM mentions")
    verified_names = [row["name"] for row in manifest_conn.execute(
        "SELECT name FROM files WHERE status='verified' ORDER BY name")]
    expected = [row["name"] for row in files]
    scanned = 0
    skipped = 0
    found = []
    for name in verified_names:
        path = os.path.join(RAW, name)
        with zipfile.ZipFile(path) as archive:
            member = archive.namelist()[0]
            for raw in archive.open(member):
                scanned += 1
                article = parse_gkg_line(raw.decode("utf-8", "replace"))
                if article is None:
                    skipped += 1
                    continue
                for company in companies:
                    org, kind, term = matching_org(article["organizations"], company["terms"])
                    if org is None:
                        continue
                    found.append({
                        "cik": company["cik"],
                        "snapshot": company["snapshot"].isoformat(),
                        "adsh": company["adsh"],
                        "url": article["url"],
                        "observed_at": article["observed_at"],
                        "source": article["source"],
                        "tone": article["tone"],
                        "themes": article["acquisition_themes"],
                        "org": org,
                        "kind": kind,
                        "term": term,
                        "file_name": name,
                        "published_at": article["published_at"],
                    })
        print("parsed", name, "matches", len(found), flush=True)
    deduped = {}
    dropped = 0
    for row in found:
        key = (row["cik"], row["snapshot"], row["adsh"], row["url"])
        current = deduped.get(key)
        if current is None or row["observed_at"] < current["observed_at"]:
            if current is not None:
                dropped += 1
            deduped[key] = row
        else:
            dropped += 1
    conn.executemany(
        """INSERT INTO mentions (
            cik, snapshot_date, adsh, url, observed_at, source, tone, acquisition_themes,
            matched_org, matched_kind, matched_term, file_name, published_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(row["cik"], row["snapshot"], row["adsh"], row["url"],
          row["observed_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), row["source"], row["tone"],
          ";".join(row["themes"]), row["org"][:200], row["kind"], row["term"],
          row["file_name"], row["published_at"]) for row in deduped.values()],
    )
    conn.execute(
        "INSERT OR REPLACE INTO parse_notes (name, detail) VALUES ('scan', ?)",
        (json.dumps({"rows": scanned, "short_rows": skipped, "duplicate_mentions": dropped,
                     "expected_files": expected, "verified_files": verified_names}),),
    )
    conn.commit()
    return expected, verified_names


def build_features(conn, companies, expected, verified_names):
    conn.execute("DELETE FROM features")
    complete = day_complete(expected, verified_names)
    for company in companies:
        rows = conn.execute(
            """SELECT observed_at, source, tone, acquisition_themes FROM mentions
               WHERE cik=? AND snapshot_date=? AND adsh=?""",
            (company["cik"], company["snapshot"].isoformat(), company["adsh"]),
        ).fetchall()
        mentions = []
        discarded = 0
        for row in rows:
            observed = datetime.strptime(row["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if observed.date() > company["snapshot"]:
                discarded += 1
                continue
            mentions.append({
                "observed_at": observed,
                "source": row["source"],
                "tone": row["tone"],
                "acquisition_themes": [item for item in (row["acquisition_themes"] or "").split(";") if item],
            })
        joined = join_day(mentions, company["snapshot"], ARCHIVE_DAY, complete)
        counts = {}
        if joined["reason"] == "observed":
            counts[ARCHIVE_DAY] = joined["mentions"]
        conn.execute(
            """INSERT INTO features (
                cik, snapshot_date, adsh, mentions, sources, tone, acquisition_mentions,
                change_7, change_30, change_90, reason, discarded_after_cutoff
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company["cik"], company["snapshot"].isoformat(), company["adsh"],
             joined["mentions"], joined["sources"], joined["tone"], joined["acquisition_mentions"],
             rolling_change(counts, company["snapshot"], 7),
             rolling_change(counts, company["snapshot"], 30),
             rolling_change(counts, company["snapshot"], 90),
             joined["reason"], discarded),
        )
    conn.commit()


def sec_available(companies):
    sec = sqlite3.connect(SEC_DB)
    sec.row_factory = sqlite3.Row
    found = 0
    for company in companies:
        if company["kind"] == "target":
            row = sec.execute(
                """SELECT last_close, revenue, assets FROM historical_company_snapshots
                   WHERE announcement_adsh=? AND kind='target_pre' AND snapshot_date=?""",
                (company["adsh"], company["snapshot"].isoformat()),
            ).fetchone()
        else:
            row = sec.execute(
                """SELECT last_close, revenue, assets FROM historical_company_snapshots
                   WHERE cik=? AND kind='non_acquired' AND snapshot_date=?""",
                (company["cik"], company["snapshot"].isoformat()),
            ).fetchone()
        if row and (row["last_close"] is not None or row["revenue"] is not None or row["assets"] is not None):
            found += 1
    sec.close()
    return found


def write_reports(conn, manifest_conn, companies):
    os.makedirs(REPORTS, exist_ok=True)
    files = manifest_conn.execute("SELECT status, COUNT(*) n FROM files GROUP BY status").fetchall()
    failed = manifest_conn.execute(
        "SELECT name, http_status, detail FROM files WHERE status!='verified' ORDER BY name").fetchall()
    scan = json.loads(conn.execute("SELECT detail FROM parse_notes WHERE name='scan'").fetchone()["detail"])
    feature_rows = conn.execute(
        """SELECT c.name, c.ticker, c.kind, c.cohort, c.label, c.snapshot_date, f.mentions, f.sources,
                  f.tone, f.acquisition_mentions, f.change_7, f.change_30, f.change_90, f.reason,
                  f.discarded_after_cutoff
           FROM features f JOIN companies c
             ON c.cik=f.cik AND c.snapshot_date=f.snapshot_date AND c.adsh=f.adsh
           ORDER BY c.cohort, c.snapshot_date, c.name"""
    ).fetchall()
    mentions = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
    published = conn.execute("SELECT COUNT(*) FROM mentions WHERE published_at IS NOT NULL").fetchone()[0]
    companies_with_mentions = conn.execute("SELECT COUNT(DISTINCT cik) FROM mentions").fetchone()[0]
    observed = [row for row in feature_rows if row["reason"] == "observed"]
    positives = [row for row in observed if row["label"] == 1]
    negatives = [row for row in observed if row["label"] == 0]
    counts = {
        "rows": len(observed),
        "positives": len(positives),
        "negatives": len(negatives),
        "holdout": int(len(observed) * 0.3),
    }
    ready, missing = acquisition_ready(counts)
    sec_rows = sec_available(companies)
    text = {
        "gdelt_bulk_pilot.md": pilot_report(files, scan, feature_rows, mentions, companies_with_mentions),
        "gdelt_bulk_data_quality.md": quality_report(files, failed, scan, feature_rows, mentions, published),
        "gdelt_bulk_model_comparison.md": comparison_report(counts, ready, missing, sec_rows, observed),
    }
    for name, body in text.items():
        with open(os.path.join(REPORTS, name), "w", encoding="utf-8") as handle:
            handle.write(body)
    print("reports", mentions, "mentions", len(observed), "observed companies", flush=True)


def _table(rows):
    if not rows:
        return "None.\n"
    return "".join("- %s\n" % row for row in rows)


def pilot_report(files, scan, feature_rows, mentions, companies_with_mentions):
    file_lines = ", ".join("%s=%s" % (row["status"], row["n"]) for row in files) or "none"
    company_lines = []
    for row in feature_rows:
        company_lines.append(
            "%s (%s), %s, snapshot %s, label %s, mentions %s, sources %s, tone %s, acquisition themes %s, reason %s, discarded after cutoff %s"
            % (row["name"], row["ticker"], row["kind"], row["snapshot_date"], row["label"],
               row["mentions"], row["sources"], None if row["tone"] is None else round(row["tone"], 3),
               row["acquisition_mentions"], row["reason"], row["discarded_after_cutoff"])
        )
    return """# GDELT bulk pilot

Checked %s. The DOC search API was not called. No production score was changed.

## Archive

GDELT 2.0 publishes three files every 15 minutes. `lastupdate.txt` lists the newest export, mentions, and GKG zip. `masterfilelist.txt` is the historical index, 129,349,356 bytes on this check. It was streamed and not stored. Each index line is a size, an MD5, and a URL.

The pilot uses the GKG files only. GKG carries the source, the article URL, organization names, themes, and tone. The pilot day is 3 February 2021 UTC, because that day falls on or before the stored prediction dates for a group of SEC companies and is small enough to keep. The 96 files for that day are about 717MB compressed. A 7-day or 90-day archive was not downloaded.

File status: %s.

GKG rows scanned: %s. Rows too short to parse: %s. Duplicate company-article rows dropped: %s.

## Companies

The pilot uses companies already in the SEC tables. In-window companies have a prediction date on or after 3 February 2021, so this day's processing time is allowed. Before-cutoff companies have a prediction date of 1 or 2 February, so the same files are after their cutoff.

Matched mention rows: %s. Companies with at least one matched URL: %s.

%s
## What was joined

Each mention is stored with the SEC CIK and the prediction date. The raw zips stay in `data/historical/gdelt_bulk/raw`. The company rows, matches, and features are in `data/historical/gdelt_bulk/pilot.sqlite`. A mention is not a probability.

Rolling 7-day, 30-day, and 90-day changes are empty for every company. Those windows include days that were not downloaded. The empty value is missing coverage, not a change of zero.
""" % (
        iso_now(), file_lines, scan["rows"], scan["short_rows"], scan["duplicate_mentions"],
        mentions, companies_with_mentions, _table(company_lines),
    )


def quality_report(files, failed, scan, feature_rows, mentions, published):
    failed_lines = ["%s HTTP %s %s" % (row["name"], row["http_status"], row["detail"] or "") for row in failed]
    zeros = sum(1 for row in feature_rows if row["reason"] == "observed" and row["mentions"] == 0)
    observed = sum(1 for row in feature_rows if row["reason"] == "observed")
    after = sum(1 for row in feature_rows if row["reason"] == "archive_after_cutoff")
    incomplete = sum(1 for row in feature_rows if row["reason"] == "incomplete_archive")
    discarded = sum(row["discarded_after_cutoff"] or 0 for row in feature_rows)
    return """# GDELT bulk data quality

## Coverage

Files in the 3 February 2021 GKG index: %s.
Verified files match the index size and MD5. A download that fails, including HTTP 429, is not retried when the status is 429. A server error can be retried up to three times with exponential backoff and jitter. A failed slot is recorded and is not read as an empty news file.

Failed or unverified files:
%s
## Timestamps

GKG `DATE` is the 15-minute time GDELT processed the file. It is stored as the observation time. The file has a `Dates` column of dates mentioned in the text, and some URLs contain a path date. Neither is stored as the publisher's publication time. Mention rows with a publication time: %s of %s.

## Matches

Organization names come from the GKG organization fields. A cleaned SEC name or a listed alias must appear as consecutive tokens. Alphabet also matches Google. A ticker matches only when it is the entire organization name, so OTIS does not match Otis Technology. One article URL is stored once per company. A second 15-minute copy of the same URL is dropped.

Rows scanned: %s. Short rows: %s. Duplicate mention rows dropped: %s. Mention rows kept: %s.

## Missing versus zero

Companies with a complete archive day on or before the prediction date: %s. Of those, explicit zero mentions: %s.
Companies whose prediction date is before the archive day: %s. Their mention count is empty. Matched articles discarded because the observation time is after the prediction date: %s.
Companies left empty because the archive day is incomplete: %s.

A zero appears only when every indexed file for the day verified and the company had no matching organization.
""" % (
        sum(row["n"] for row in files),
        _table(failed_lines) if failed_lines else "None.\n",
        published, mentions, scan["rows"], scan["short_rows"], scan["duplicate_mentions"], mentions,
        observed, zeros, after, discarded, incomplete,
    )


def comparison_report(counts, ready, missing, sec_rows, observed):
    header = """# GDELT bulk model comparison

The prediction date is the SEC snapshot: 30 days before a verified announcement, or the stored date for a company that was not acquired. The label is an announcement inside the next 30 days. News features may use only GKG rows processed on or before that date.

Pilot companies with an observed mention count: %d. Positives: %d. Negatives: %d. A 30 percent holdout would be %d rows. Companies that also have a SEC price or a SEC statement on the snapshot: %d.

""" % (counts["rows"], counts["positives"], counts["negatives"], counts["holdout"], sec_rows)
    if not ready:
        return header + """## Result

The comparison was not scored. The pilot does not clear the existing acquisition gate (%s). No model was fit. SEC-only and SEC-plus-GDELT probabilities were not produced. The bulk archive was downloaded, parsed, and joined. That is not evidence that the news features improve a forecast.

The gate is 100 rows, 20 positives, 20 negatives, and 15 holdout rows. The 7-day, 30-day, and 90-day coverage changes are also missing, because only one UTC day was downloaded.
""" % (", ".join(missing) if missing else "the sample")
    return header + "The gate passed. This pilot script does not save a model.\n"


def main():
    files = load_index()
    companies = select_companies()
    print("files", len(files), "companies", len(companies), flush=True)
    manifest_conn = manifest()
    if "--parse-only" not in sys.argv:
        download_all(files, manifest_conn)
    conn = pilot_db()
    store_companies(conn, companies)
    expected, verified_names = parse_verified(files, companies, manifest_conn, conn)
    build_features(conn, companies, expected, verified_names)
    write_reports(conn, manifest_conn, companies)
    conn.close()
    manifest_conn.close()


if __name__ == "__main__":
    main()
