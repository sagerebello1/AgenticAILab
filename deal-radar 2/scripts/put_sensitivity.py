"""Write the hypothetical OTM put sensitivity report. Does not fetch prices.

    python3 scripts/put_sensitivity.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from historical.put_sensitivity import measure, render  # noqa: E402

OUT = os.path.join(ROOT, "reports", "otm_put_sensitivity.md")


def main():
    parser = argparse.ArgumentParser(description="Hypothetical OTM put sensitivity.")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    report = render(measure())
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(args.out)


if __name__ == "__main__":
    main()
