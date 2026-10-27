"""Builds dist/deal-radar-demo.html: the interface with the sample deals baked in.

The result works as a plain file (double-click it) in sample mode. It cannot reach EDGAR or
Dealroom on its own; for live data run server.py instead.
"""
import json
import os

import news
import sample_data

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "static", "app.html"), encoding="utf-8") as f:
    body = f.read()
body = body.replace("/*__SAMPLE__*/[]", json.dumps(sample_data.sample_deals()))
body = body.replace("/*__NEWSCFG__*/{}", json.dumps(news.config()))
os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + body + "</body></html>")
with open(os.path.join(HERE, "dist", "deal-radar-demo.html"), "w", encoding="utf-8") as f:
    f.write(page)
with open(os.path.join(HERE, "dist", "deal-radar-fragment.html"), "w", encoding="utf-8") as f:
    f.write(body)
print("wrote dist/deal-radar-demo.html and dist/deal-radar-fragment.html")
