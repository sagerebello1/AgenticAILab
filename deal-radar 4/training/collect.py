"""Step 1: download the raw material from SEC EDGAR. Resumable: run it again and it skips what it has.

    python3 training/collect.py candidates --start 2005-01-01     # find merger-agreement 8-Ks
    python3 training/collect.py text                              # download each announcement
    python3 training/collect.py submissions                       # download each company's filing history

Everything lands in data/ next to server.py. Expect hours for a full history because the SEC allows
about 10 requests per second and this script stays under that. You can stop it with Ctrl+C at any time.
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta

from common import ROOT, append_jsonl, data_dir, read_gz, read_jsonl, user_agent, write_gz  # noqa: F401
import edgar
import terms

QUERIES = ['"agreement and plan of merger"', '"agreement and plan of reorganization"', '"merger agreement"']


def stage_candidates(args):
    ua = user_agent()
    out = os.path.join(data_dir(), "candidates.jsonl")
    done_path = os.path.join(data_dir(), "windows_done.txt")
    done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()
    known = {r["adsh"] for r in read_jsonl(out)}
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end) if args.end else date.today()
    cur = start
    while cur < end:
        win_end = min(cur + timedelta(days=args.window - 1), end)
        key = cur.isoformat()
        if key not in done:
            rows = []
            for q in QUERIES:
                offset, total = 0, 1
                while offset < min(total, 10000):
                    try:
                        recs, total = edgar.search_window(ua, cur, win_end, q, "8-K", offset)
                    except edgar.EdgarError as e:
                        print("  skipped %s %s: %s" % (key, q, e), file=sys.stderr)
                        break
                    if not recs:
                        break
                    rows += [r for r in recs if "1.01" in r["items"] and r["adsh"] not in known]
                    known.update(r["adsh"] for r in recs)
                    offset += 100
            append_jsonl(out, rows)
            with open(done_path, "a") as f:
                f.write(key + "\n")
            print("%s to %s: %d new candidates" % (key, win_end, len(rows)))
        cur = win_end + timedelta(days=1)


def stage_text(args):
    ua = user_agent()
    cands = read_jsonl(os.path.join(data_dir(), "candidates.jsonl"))
    tdir = data_dir("text")
    n = 0
    for r in cands:
        path = os.path.join(tdir, r["adsh"] + ".txt.gz")
        if os.path.exists(path) or not r["docUrl"]:
            continue
        try:
            text = terms.to_text(edgar.fetch_document(ua, r["docUrl"], max_bytes=3_000_000))
        except edgar.EdgarError as e:
            print("  skipped %s: %s" % (r["adsh"], e), file=sys.stderr)
            continue
        write_gz(path, text[:250_000])
        n += 1
        if n % 200 == 0:
            print("downloaded %d announcements" % n)
        if args.limit and n >= args.limit:
            break
    print("done, %d new" % n)


def stage_submissions(args):
    ua = user_agent()
    cands = read_jsonl(os.path.join(data_dir(), "candidates.jsonl"))
    sdir = data_dir("submissions")
    ciks = sorted({r["cik"] for r in cands})
    n = 0
    for cik in ciks:
        path = os.path.join(sdir, "%d.json" % cik)
        if os.path.exists(path):
            continue
        try:
            sub = edgar.submissions(ua, cik)
        except edgar.EdgarError as e:
            print("  skipped %d: %s" % (cik, e), file=sys.stderr)
            continue
        with open(path, "w") as f:
            json.dump(sub, f)
        n += 1
        if n % 200 == 0:
            print("downloaded %d company histories of %d" % (n, len(ciks)))
        if args.limit and n >= args.limit:
            break
    print("done, %d new" % n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["candidates", "text", "submissions"])
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--window", type=int, default=7, help="days per search window")
    ap.add_argument("--limit", type=int, default=0, help="stop after N downloads (for a trial run)")
    a = ap.parse_args()
    {"candidates": stage_candidates, "text": stage_text, "submissions": stage_submissions}[a.stage](a)
