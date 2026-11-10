"""Step 2: decide, for each announced deal, whether it closed or was terminated.

EDGAR has no single "deal outcome" field, so the outcome is inferred from what the company filed next:

  closed      the first of: an 8-K with Item 2.01 (completed acquisition) or Item 5.01 (change in control),
              or a Form 25 / Form 15-12B / 15-12G (the stock stopped trading and registration ended)
  terminated  an 8-K with Item 1.02 (termination of a material agreement) whose text says the merger
              agreement was terminated (checked when --verify is used)
  dropped     nothing decisive within 540 days, or the window has not finished yet

The first decisive filing after the announcement wins. This is a proxy and it has known weak spots,
listed in the README. Run with --audit 30 to print 30 random labelled deals and check them by hand.

    python3 training/label.py [--verify] [--audit 30]
"""
import argparse
import json
import os
import random
import re
import sys
from datetime import date

from common import data_dir, read_gz, read_jsonl, user_agent
import edgar
import terms

WINDOW_DAYS = 540
CLOSE_FORMS = ("25", "25-NSE", "15-12B", "15-12G")
TERM_RX = re.compile(r"terminat", re.I)
MERGER_RX = re.compile(r"merger\s+agreement|agreement\s+and\s+plan\s+of\s+(?:merger|reorganization)", re.I)


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def resolve(filings, announced, verify_term=None):
    """Return (label, days, evidence) where label is 1 closed, 0 terminated, or None."""
    for f in filings:
        if f["date"] <= announced:
            continue
        d = days_between(announced, f["date"])
        if d > WINDOW_DAYS:
            break
        items = set(f["items"])
        if f["form"] in CLOSE_FORMS or (f["form"] == "8-K" and items & {"2.01", "5.01"}):
            return 1, d, "%s %s" % (f["form"], f["date"])
        if f["form"] == "8-K" and "1.02" in items:
            if verify_term is None or verify_term(f):
                return 0, d, "8-K 1.02 %s" % f["date"]
    return None, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="download each Item 1.02 8-K to confirm it ends a merger agreement")
    ap.add_argument("--audit", type=int, default=0)
    a = ap.parse_args()

    ua = user_agent() if a.verify else None
    cands = sorted(read_jsonl(os.path.join(data_dir(), "candidates.jsonl")), key=lambda r: r["filedOn"])
    sdir, tdir = data_dir("submissions"), data_dir("text")
    today = date.today().isoformat()
    cache = {}

    def verify_term(f):
        path = os.path.join(data_dir("term_docs"), f["adsh"] + ".txt")
        if not os.path.exists(path):
            try:
                url = "%s/%d/%s/%s" % (edgar.ARCHIVES, cache["cik"], f["adsh"].replace("-", ""), f["doc"])
                text = terms.to_text(edgar.fetch_document(ua, url))[:60000]
            except edgar.EdgarError:
                return False
            open(path, "w", encoding="utf-8").write(text)
        text = open(path, encoding="utf-8").read()
        return bool(TERM_RX.search(text) and MERGER_RX.search(text))

    out, last_kept, skipped = [], {}, {"no history": 0, "dup": 0, "open": 0, "no text": 0}
    for r in cands:
        spath = os.path.join(sdir, "%d.json" % r["cik"])
        if not os.path.exists(spath) or not os.path.exists(os.path.join(tdir, r["adsh"] + ".txt.gz")):
            skipped["no history" if not os.path.exists(spath) else "no text"] += 1
            continue
        prev = last_kept.get(r["cik"])
        if prev and days_between(prev, r["filedOn"]) < WINDOW_DAYS:
            skipped["dup"] += 1     # amended or repeated announcement of the same deal
            continue
        sub = json.load(open(spath))
        cache["cik"] = r["cik"]
        label, days, ev = resolve(sub["filings"], r["filedOn"], verify_term if a.verify else None)
        if label is None:
            skipped["open"] += 1
            continue
        last_kept[r["cik"]] = r["filedOn"]
        out.append({"adsh": r["adsh"], "cik": r["cik"], "filer": r["filer"], "ticker": r["ticker"], "filedOn": r["filedOn"],
                    "sic": sub.get("sic"), "label": label, "days": days, "evidence": ev})
    with open(os.path.join(data_dir(), "labels.jsonl"), "w") as f:
        for row in out:
            f.write(json.dumps(row) + "\n")
    closed = sum(r["label"] for r in out)
    print("labelled %d deals: %d closed, %d terminated (%.1f%% closed)" % (len(out), closed, len(out) - closed, 100 * closed / max(len(out), 1)))
    print("not used:", skipped)
    if a.audit:
        print("\nAudit sample. Open each filing and check the label by hand:")
        for r in random.sample(out, min(a.audit, len(out))):
            print("%s %-35s %s after %3d days via %s" % (r["filedOn"], (r["filer"] or "")[:35], "CLOSED    " if r["label"] else "TERMINATED", r["days"], r["evidence"]))


if __name__ == "__main__":
    main()
