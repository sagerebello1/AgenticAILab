"""Options research math. No network and no orders."""
import json
from datetime import datetime, timedelta, timezone

import market
import options
import server


def labels(contract):
    return [s["label"] for s in contract["signals"]]


def test_chain_is_unavailable_and_not_bypassed():
    assert options.CHAIN["available"] is False
    assert options.CHAIN["http"] == 401
    quote, note = market.contract("PAG", "call", 200, 30)
    assert quote is None
    assert "401" in note


def test_call_and_put_expiration_payoffs_use_the_ask_and_the_multiplier():
    report = options.analyze({
        "spot": 45.9, "offer": 50, "downside": 40, "filingStatus": "extracted",
        "catalyst": {"kind": "terms_quoted", "label": "Cash price quoted from a filing", "confirmed": True},
        "call": {"strike": 46, "days": 30, "bid": 1.0, "ask": 1.5, "multiplier": 100, "deliverable": 100},
        "put": {"strike": 46, "days": 30, "bid": 2.0, "ask": 2.5, "multiplier": 100, "deliverable": 100},
    })
    call, put = report["call"], report["put"]
    assert call["breakEven"] == 47.5
    assert put["breakEven"] == 43.5
    assert call["maxLoss"] == 150
    assert put["maxLoss"] == 250
    assert call["liveOpportunity"] is False and put["liveOpportunity"] is False
    assert call["quoteState"] == "manual"
    close = next(s for s in call["scenarios"] if s["price"] == 50)
    assert close["contract"] == (50 - 46 - 1.5) * 100
    assert "Not a value before expiration" in close["label"]
    assert "Research candidate" in labels(call)
    assert report["placesTrades"] is False
    assert "not multiplied" in report["pCloseNote"]


def test_call_above_the_offer_has_no_verified_edge():
    call = options.analyze_contract("call", {"strike": 46, "days": 30, "ask": 1.5}, {
        "spot": 45.9, "offer": 44.8, "catalyst": {"kind": "terms_quoted", "confirmed": True}})
    assert call["breakEven"] == 47.5
    assert "No verified edge" in labels(call)
    assert "Research candidate" not in labels(call)


def test_put_worthless_at_the_offer_has_no_verified_edge():
    put = options.analyze_contract("put", {"strike": 40, "days": 30, "ask": 1}, {
        "spot": 45.9, "offer": 44.8, "catalyst": {"kind": "terms_quoted", "confirmed": True}})
    assert "No verified edge" in labels(put)
    covered = options.analyze_contract("put", {"strike": 46, "days": 30, "ask": 2}, {
        "spot": 45.9, "offer": 44.8, "catalyst": {"kind": "terms_quoted", "confirmed": True}})
    assert "No verified edge" in labels(covered)
    assert "Research candidate" not in labels(covered)


def test_missing_ask_does_not_invent_a_premium():
    call = options.analyze_contract("call", {"strike": 46, "days": 30}, {"spot": 45.9})
    assert call["premium"] is None
    assert call["breakEven"] is None
    assert call["greeks"] is None
    assert call["quoteState"] == "unavailable"
    assert "Insufficient options data" in labels(call)


def test_stale_timestamp_is_rejected():
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    call = options.analyze_contract("call", {"strike": 46, "days": 30, "ask": 1, "quotedAt": old}, {"spot": 45})
    assert call["premium"] is None
    assert any("20 minutes" in e for e in call["errors"])
    assert call["liveOpportunity"] is False


def test_greeks_stay_unavailable_without_implied_volatility():
    call = options.analyze_contract("call", {"strike": 100, "days": 365, "ask": 5}, {
        "spot": 100, "offer": 120, "catalyst": {"kind": "terms_quoted", "confirmed": True}})
    assert call["iv"] is None and call["greeks"] is None
    g = options.greeks(100, 100, 365, 0.045, 0.20, "call")
    assert g["source"] == "calculated"
    assert 0.5 < g["delta"] < 0.8
    assert options.greeks(100, 100, 365, 0.045, None, "call") is None


def test_nonstandard_deliverable_is_flagged():
    call = options.analyze_contract("call", {
        "strike": 50, "days": 10, "ask": 2, "multiplier": 100, "deliverable": 50}, {"spot": 55, "offer": 60,
        "catalyst": {"kind": "terms_quoted", "confirmed": True}})
    assert call["nonstandard"] is True
    assert call["maxLoss"] == 200
    assert "High event risk" in labels(call)


def test_unverified_filing_is_not_a_research_candidate():
    call = options.analyze_contract("call", {"strike": 10, "days": 40, "ask": 0.4}, {
        "spot": 10, "offer": None, "catalyst": {"kind": "termination", "label": "Deal termination", "confirmed": False}})
    assert "Research candidate" not in labels(call)
    assert "Deal status changed" in labels(call)
    assert "No verified edge" in labels(call)


def test_live_scan_without_an_agent_does_not_substitute_sample_deals():
    saved = server.EDGAR_UA
    server.EDGAR_UA = ""
    try:
        out = server.scan(7, 3)
    finally:
        server.EDGAR_UA = saved
    assert out["mode"] == "error"
    assert out["deals"] == []
    assert "Marrow" not in json.dumps(out)


def _capture_options(body):
    handler = server.Handler.__new__(server.Handler)
    sent = {}

    def capture(code, payload, ctype="application/json"):
        sent["code"] = code
        sent["payload"] = payload

    handler._send = capture
    handler._options_research(body)
    return sent


def _cash_put():
    return {
        "spot": 50, "offer": 60, "downside": 32, "rate": 0.045, "bump": 0,
        "consideration": "cash", "daysToClose": 180,
        "pClose": 0.9, "pPending": 0.84,
        "filingStatus": "extracted",
        "catalyst": {"kind": "terms_quoted", "label": "Cash price quoted from a filing", "confirmed": True},
        "call": {"strike": 40, "days": 30, "bid": 1.5, "ask": 2},
        "put": {"strike": 40, "days": 30, "bid": 1.0, "ask": 1.1, "iv": 0.35},
    }


def test_options_endpoint_adds_the_put_benchmark_without_dropping_payoffs():
    sent = _capture_options(_cash_put())
    assert sent["code"] == 200
    body = sent["payload"]
    for key in ("chain", "catalyst", "pClose", "pCloseNote", "call", "put", "placesTrades"):
        assert key in body
    assert body["placesTrades"] is False
    assert "not multiplied" in body["pCloseNote"]
    assert body["put"]["breakEven"] == 38.9
    assert body["put"]["maxLoss"] == 110
    assert body["call"]["quoteState"] == "manual"
    close = next(row for row in body["put"]["scenarios"] if row["name"] == "If the deal closes at the offer")
    assert close["contract"] == round((max(40 - 60, 0) - 1.1) * 100, 2)
    bench = body["putBenchmark"]
    assert bench["consideration"] == "cash"
    assert bench["acquisitionLevel"] == 60
    assert bench["blackScholes"] > 0
    assert bench["maAware"] is not None
    assert abs(bench["absoluteDifference"] - (bench["maAware"] - bench["blackScholes"])) < 1e-12
    assert abs(bench["percentDifference"] - bench["absoluteDifference"] / bench["blackScholes"]) < 1e-12
    assert bench["marketPremium"] == 1.1
    assert bench["expiresBeforeClose"] is True
    assert {row["key"] for row in bench["scenarios"]} == {"close", "pending", "break"}
    assert abs(sum(row["weight"] for row in bench["scenarios"]) - 1) < 1e-12
    assert bench["pClose"] == 0.9
    assert "more accurate" in " ".join(bench["notes"])
    assert "not been validated" in " ".join(bench["notes"])


def test_options_endpoint_leaves_missing_benchmark_inputs_missing():
    sent = _capture_options({
        "spot": 50, "downside": 32, "consideration": "cash",
        "put": {"strike": 40, "days": 30},
        "call": {"strike": 40, "days": 30},
    })
    body = sent["payload"]
    assert body["put"]["premium"] is None
    assert body["put"]["breakEven"] is None
    assert body["put"]["greeks"] is None
    assert body["call"]["quoteState"] == "unavailable"
    bench = body["putBenchmark"]
    assert bench["maAware"] is None
    assert bench["marketPremium"] is None
    assert bench["absoluteDifference"] is None
    assert bench["percentDifference"] is None
    assert bench["scenarios"] is None
    for name in ("offer", "volatility", "rate", "days_to_close", "p_close", "p_pending"):
        assert name in bench["missing"]
    assert "0.90" not in open(options.__file__, encoding="utf-8").read().split("def put_comparison", 1)[1]


def test_stock_put_benchmark_uses_the_exchange_ratio():
    body = dict(_cash_put(), consideration="stock", offer=None, exchangeRatio=0.5, acquirerPrice=80)
    sent = _capture_options(body)
    bench = sent["payload"]["putBenchmark"]
    assert bench["consideration"] == "stock"
    assert bench["acquisitionLevel"] == 40
    assert bench["maAware"] is not None
    assert "offer" not in bench["missing"]


def test_server_has_no_order_route():
    text = open(server.__file__, encoding="utf-8").read()
    assert "/api/order" not in text
    assert "place_order" not in text
    assert "submit_order" not in text


if __name__ == "__main__":
    test_chain_is_unavailable_and_not_bypassed()
    test_call_and_put_expiration_payoffs_use_the_ask_and_the_multiplier()
    test_call_above_the_offer_has_no_verified_edge()
    test_put_worthless_at_the_offer_has_no_verified_edge()
    test_missing_ask_does_not_invent_a_premium()
    test_stale_timestamp_is_rejected()
    test_greeks_stay_unavailable_without_implied_volatility()
    test_nonstandard_deliverable_is_flagged()
    test_unverified_filing_is_not_a_research_candidate()
    test_live_scan_without_an_agent_does_not_substitute_sample_deals()
    test_options_endpoint_adds_the_put_benchmark_without_dropping_payoffs()
    test_options_endpoint_leaves_missing_benchmark_inputs_missing()
    test_stock_put_benchmark_uses_the_exchange_ratio()
    test_server_has_no_order_route()
    print("ok")
