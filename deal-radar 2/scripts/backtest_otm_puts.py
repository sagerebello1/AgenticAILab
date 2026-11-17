"""Write the historical OTM put coverage report. Does not train a model or fetch prices.

    python3 scripts/backtest_otm_puts.py
"""
import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from historical.put_backtest import measure, render  # noqa: E402

DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
OUT = os.path.join(ROOT, "reports", "otm_put_realized_payoff.md")


def connect_readonly(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def main():
    parser = argparse.ArgumentParser(description="Historical put coverage and realized payoffs.")
    parser.add_argument("--db", default=DB)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    if not os.path.exists(args.db):
        raise SystemExit("Historical database not found: %s" % args.db)
    conn = connect_readonly(args.db)
    conn.row_factory = sqlite3.Row
    try:
        report = render(measure(conn))
    finally:
        conn.close()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(args.out)


if __name__ == "__main__":
    main()
