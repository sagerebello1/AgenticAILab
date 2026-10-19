"""Not used by the server. Dealroom requires a paid account, so Deal Radar does not call it.

Dealroom connector (dealroom.co, the venture and startup data provider).

Dealroom's REST API uses OAuth2 client credentials:
  1. POST https://accounts.dealroom.co/oauth/token with client_id, client_secret, audience and
     grant_type=client_credentials. The token lasts about 24 hours, so it is cached here.
  2. Send every request with "Authorization: Bearer <token>" and "X-Client-Id: <client id>".

Keys are issued on request through Dealroom, and its own documentation says it is still
changing. The docs show two hosts (api.dealroom.app with /data/... paths, and
api-next.dealroom.co with /api/data/... paths), so this client tries both path styles and
you can point it at a different host with DEALROOM_BASE_URL. I could not test it without a
key. If a call fails, the app shows "no Dealroom match" instead of stopping.

Coverage note: Dealroom is built around private and venture-backed companies. Large listed
targets will often come back empty. It is most useful for startups and mid-size private
companies that appear in a deal.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://accounts.dealroom.co/oauth/token"
UA = "DealRadar/1.0 (+student research prototype)"


class DealroomError(Exception):
    pass


class Dealroom:
    def __init__(self, client_id, client_secret, base_url="https://api.dealroom.app", audience="https://api.dealroom.app"):
        self.client_id, self.secret = client_id, client_secret
        self.base, self.audience = base_url.rstrip("/"), audience
        self._token, self._expires = None, 0.0

    def _request(self, url, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"User-Agent": UA, "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())

    def _bearer(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        try:
            tok = self._request(TOKEN_URL, body={
                "client_id": self.client_id, "client_secret": self.secret,
                "audience": self.audience, "grant_type": "client_credentials"})
        except urllib.error.HTTPError as e:
            raise DealroomError("Dealroom rejected the API credentials (HTTP %d)" % e.code)
        self._token = tok["access_token"]
        self._expires = time.time() + int(tok.get("expires_in", 86400))
        return self._token

    def _get(self, path, params=None):
        url = self.base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        headers = {"Authorization": "Bearer " + self._bearer(), "X-Client-Id": self.client_id}
        try:
            return self._request(url, headers=headers)
        except urllib.error.HTTPError as e:
            if e.code == 401:  # token may have been revoked or expired early: refresh once
                self._token = None
                headers["Authorization"] = "Bearer " + self._bearer()
                return self._request(url, headers=headers)
            raise

    def _try_paths(self, paths, params=None):
        last = None
        for path in paths:
            try:
                return self._get(path, params)
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (404, 405):
                    raise
        raise last

    def find_company(self, name):
        """Best matching company profile for a name, or None."""
        found = self._try_paths(["/api/data/search", "/data/search"], {"q": name, "types": "company", "limit": 3})
        results = (found.get("data") or {}).get("results") if isinstance(found.get("data"), dict) else found.get("data")
        if not results:
            return None
        hit = results[0]
        profile = {
            "name": hit.get("name"), "tagline": hit.get("tagline"),
            "hq": ", ".join(x for x in [hit.get("hq_city"), hit.get("hq_country")] if x) or None,
            "website": hit.get("website_domain"), "uuid": hit.get("uuid"),
            "sectors": [], "valuation": None, "fundingTotal": None, "employees": None, "status": None,
            "url": None,
        }
        try:
            detail = self._try_paths(["/data/companies/%s" % hit["uuid"], "/api/data/companies/%s" % hit["uuid"]])
            d = detail.get("data", detail)
            val = d.get("valuation") or {}
            profile.update({
                "sectors": [t["name"] for t in (d.get("taxonomy") or []) if t.get("type") in ("sector", "industry")][:4],
                "valuation": val.get("value"), "valuationYear": val.get("year"),
                "fundingTotal": (d.get("funding") or {}).get("total"),
                "employees": d.get("employees_count"), "status": d.get("status"), "url": d.get("dealroom_url"),
            })
        except (urllib.error.HTTPError, KeyError):
            pass  # the search hit alone is still useful
        return profile
