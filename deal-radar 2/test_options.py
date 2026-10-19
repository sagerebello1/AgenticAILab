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
    test_server_has_no_order_route()
    print("ok")
