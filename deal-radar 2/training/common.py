"""Shared helpers for the training scripts."""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def load_env():
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def user_agent():
    load_env()
    ua = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        sys.exit("Set EDGAR_USER_AGENT in .env to your name and email. The SEC requires it.")
    return ua


def data_dir(sub=""):
    d = os.path.join(ROOT, "data", sub) if sub else os.path.join(ROOT, "data")
    os.makedirs(d, exist_ok=True)
    return d


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, rows):
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def write_gz(path, text):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)


def read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()
