"""Optional language-model step for the agent.

Rules (terms.py) are fast and free but brittle: merger agreements phrase things many ways.
When ANTHROPIC_API_KEY is set, this module asks a Claude model to read the filing and return
the same fields as terms.extract_terms, as JSON. Anything it cannot find stays null, and the
app then falls back to what the rules found. The probability rules in terms.py are applied
to the result either way, so the model only reads the filing; it does not set the odds.

The model name comes from LLM_MODEL (default below). I could not run this path in the build
environment because there was no API key, so treat it as untested until you try it.
"""
import json
import re
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"

PROMPT = """You are reading part of an SEC filing about a possible merger or acquisition. Extract only facts that
are stated in the text. Reply with one JSON object and nothing else, using null when a fact is not stated.

{
  "target": "name of the company being acquired",
  "acquirer": "name of the company buying it",
  "offer": number or null,                  // price per target share, in dollars
  "consideration": "cash" | "stock" | "mixed" | null,
  "expectedClose": "YYYY-MM-DD" or null,    // use the last day of the stated period
  "flags": {
    "hsr": true/false,
    "secondRequest": true/false,
    "foreign": ["CFIUS", "China SAMR", "European Commission", "UK CMA"],   // only those mentioned as required
    "other": ["named industry regulators required"],
    "financingCondition": true/false/null,  // is closing conditioned on the buyer obtaining financing?
    "tender": true/false,                   // structured as a tender offer
    "vote": true/false,                     // needs a target shareholder vote
    "goShop": true/false,
    "termFees": ["fee amounts as written"]
  }
}

Filing text:
"""


def extract(text, api_key, model=None, timeout=60):
    body = json.dumps({
        "model": model or DEFAULT_MODEL, "max_tokens": 900,
        "messages": [{"role": "user", "content": PROMPT + text[:60000]}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read())
        raw = "".join(b.get("text", "") for b in reply.get("content", []))
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return None
