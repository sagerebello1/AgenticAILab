"""GDELT 2.0 GKG bulk files. This module does not download data and does not fit a model.

The GKG DATE column is when GDELT processed the article. It is not the publisher's
publication time. A failed file is missing coverage, not a day with no news.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone


RETRYABLE = {500, 502, 503, 504}
ACQUISITION_MARKERS = ("ACQUISITION", "MERGER", "TAKEOVER", "BUYOUT", "STRATEGIC_ALTERNATIVE")
# Alphabet is filed under that name and is covered in GKG as Google.
ALIASES = {1652044: ("Google",)}


def parse_index_line(line):
    parts = line.split()
    if len(parts) != 3:
        raise ValueError("An index line needs a size, a checksum, and a URL.")
    name = parts[2].rstrip("/").split("/")[-1]
    return {"size": int(parts[0]), "md5": parts[1].lower(), "url": parts[2], "name": name}


def https_url(url):
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def gkg_files_for_day(rows, day):
    prefix = day.strftime("%Y%m%d")
    chosen = [row for row in rows
              if row["name"].startswith(prefix) and row["name"].endswith(".gkg.csv.zip")]
    return sorted(chosen, key=lambda row: row["name"])


def should_retry(status, attempt, max_attempts=3):
    """HTTP 429 is never retried. Other temporary failures get a short bounded retry."""
    if status == 429:
        return False
    if attempt + 1 >= max_attempts:
        return False
    return status in RETRYABLE or status is None


def backoff_seconds(attempt, jitter):
    base = min(30, 2 ** attempt)
    return base + jitter


def file_md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified(path, expected_size, expected_md5):
    try:
        size = __import__("os").path.getsize(path)
    except OSError:
        return False
    if size != expected_size or size == 0:
        return False
    return file_md5(path) == expected_md5.lower()


def observation_stamp(value):
    text = (value or "").strip()
    if len(text) < 14 or not text[:14].isdigit():
        return None
    stamp = datetime(int(text[0:4]), int(text[4:6]), int(text[6:8]),
                     int(text[8:10]), int(text[10:12]), int(text[12:14]), tzinfo=timezone.utc)
    return stamp


def tone_value(field):
    if field is None or not str(field).strip():
        return None
    try:
        return float(str(field).split(",")[0])
    except ValueError:
        return None


def _pieces(field, separator):
    names = []
    for part in (field or "").split(";"):
        name = part.split(separator)[0].strip()
        if name:
            names.append(name)
    return names


def organization_names(legacy, enhanced):
    seen = []
    for name in _pieces(legacy, ",") + _pieces(enhanced, ","):
        if name not in seen:
            seen.append(name)
    return seen


def theme_codes(legacy, enhanced):
    codes = []
    for code in _pieces(legacy, ",") + _pieces(enhanced, ","):
        token = code.strip().upper()
        if token and token not in codes:
            codes.append(token)
    return codes


def acquisition_themes(codes):
    return [code for code in codes if any(marker in code for marker in ACQUISITION_MARKERS)]


def tokens(text):
    return re.findall(r"[A-Z0-9]+", (text or "").upper())


def phrase_in(org, phrase):
    org_tokens = tokens(org)
    phrase_tokens = tokens(phrase)
    width = len(phrase_tokens)
    if not width or len(org_tokens) < width:
        return False
    for start in range(len(org_tokens) - width + 1):
        if org_tokens[start:start + width] == phrase_tokens:
            return True
    return False


def match_terms(name, ticker, cik):
    from historical.gdelt import identity
    found = identity(name, ticker)
    terms = []
    if found["status"] == "queryable" and found["phrase"]:
        terms.append(("name", found["phrase"]))
    if found["ticker_term"]:
        terms.append(("ticker", found["ticker_term"]))
    for alias in ALIASES.get(int(cik), ()):
        terms.append(("alias", alias))
    return found, terms


def matching_org(orgs, terms):
    """A name or alias must appear as consecutive tokens.

    A ticker matches only when it is the entire organization name. Otherwise a short
    ticker such as OTIS also matches Otis Technology and Otis Gold.
    """
    for org in orgs:
        for kind, term in terms:
            if kind == "ticker":
                if tokens(org) == tokens(term):
                    return org, kind, term
            elif phrase_in(org, term):
                return org, kind, term
    return None, None, None


def parse_gkg_line(line):
    """One GKG row. The publication time is left empty: this file does not carry it."""
    cols = line.rstrip("\n").split("\t")
    if len(cols) < 16:
        return None
    observed = observation_stamp(cols[1])
    if observed is None or not cols[4].strip():
        return None
    codes = theme_codes(cols[7] if len(cols) > 7 else "", cols[8] if len(cols) > 8 else "")
    return {
        "record_id": cols[0],
        "observed_at": observed,
        "source": cols[3].strip() or None,
        "url": cols[4].strip(),
        "organizations": organization_names(cols[13] if len(cols) > 13 else "", cols[14] if len(cols) > 14 else ""),
        "tone": tone_value(cols[15]),
        "acquisition_themes": acquisition_themes(codes),
        "published_at": None,
    }


def keep_earliest(rows):
    """One row per article URL. A later 15-minute file does not create a second article."""
    chosen = {}
    dropped = 0
    for row in rows:
        current = chosen.get(row["url"])
        if current is None or row["observed_at"] < current["observed_at"]:
            if current is not None:
                dropped += 1
            chosen[row["url"]] = row
        else:
            dropped += 1
    return list(chosen.values()), dropped


def day_complete(expected_names, verified_names):
    return bool(expected_names) and set(expected_names) == set(verified_names)


def join_day(mentions, snapshot, day, complete):
    """Mentions whose GDELT time is after the snapshot are not a count.

    An incomplete archive is missing. A complete archive with no rows is zero.
    """
    if snapshot is None or day > snapshot:
        return {"mentions": None, "sources": None, "tone": None, "acquisition_mentions": None,
                "reason": "archive_after_cutoff"}
    if not complete:
        return {"mentions": None, "sources": None, "tone": None, "acquisition_mentions": None,
                "reason": "incomplete_archive"}
    used = [row for row in mentions if row["observed_at"].date() == day and row["observed_at"].date() <= snapshot]
    tones = [row["tone"] for row in used if row["tone"] is not None]
    sources = {row["source"] for row in used if row["source"]}
    return {
        "mentions": len(used),
        "sources": len(sources),
        "tone": None if not tones else sum(tones) / len(tones),
        "acquisition_mentions": sum(1 for row in used if row["acquisition_themes"]),
        "reason": "observed",
    }


def rolling_change(counts, end, width):
    """Recent window minus the previous window. A missing day makes the change missing."""
    recent = _window_sum(counts, end - timedelta(days=width - 1), end)
    prior = _window_sum(counts, end - timedelta(days=2 * width - 1), end - timedelta(days=width))
    if recent is None or prior is None:
        return None
    return recent - prior


def _window_sum(counts, start, end):
    total = 0
    day = start
    while day <= end:
        if day not in counts:
            return None
        total += counts[day]
        day += timedelta(days=1)
    return total
