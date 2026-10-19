"""Writes dist/deal-radar-demo.html with an empty company list.

Opening the file cannot reach SEC EDGAR. Run python3 server.py for live filings.
The page does not include fictional companies.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "static", "app.html"), encoding="utf-8") as f:
    body = f.read()
body = body.replace("/*__SAMPLE__*/[]", "[]")
os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + body + "</body></html>")
with open(os.path.join(HERE, "dist", "deal-radar-demo.html"), "w", encoding="utf-8") as f:
    f.write(page)
with open(os.path.join(HERE, "dist", "deal-radar-fragment.html"), "w", encoding="utf-8") as f:
    f.write(body)
print("wrote dist/deal-radar-demo.html and dist/deal-radar-fragment.html")
