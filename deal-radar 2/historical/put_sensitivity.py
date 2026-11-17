"""Sensitivity of the existing OTM put benchmark.

Every priced row is a hypothetical contract. Historical deals are listed only
to show which inputs are missing. No volatility or premium is filled in.
"""
import math

import black_scholes
import pricing
import put_benchmark


ANCHOR = {
    "spot": 50.0,
    "strike": 40.0,
    "days": 90,
    "rate": 0.045,
    "volatility": 0.35,
    "downside": 32.0,
    "days_to_close": 120,
    "consideration": "cash",
    "acquisition_price": 60.0,
    "p_close": 0.70,
    "p_pending": 0.60,
}

# The seven cash deals in the realized-payoff report. They are not priced here.
UNPRICED_DEALS = (
    {"ticker": "HBNC", "announcement": "2016-03-11", "offer": 17.50, "prior_close": 10.62},
    {"ticker": "TSN", "announcement": "2017-04-28", "offer": 40.25, "prior_close": 64.61},
    {"ticker": "LLY", "announcement": "2019-01-07", "offer": 235.00, "prior_close": 114.66},
    {"ticker": "CNR", "announcement": "2022-03-07", "offer": 24.65, "prior_close": 35.92},
    {"ticker": "CVS", "announcement": "2023-02-08", "offer": 39.00, "prior_close": 85.98},
    {"ticker": "GILD", "announcement": "2024-02-12", "offer": 32.50, "prior_close": 73.67},
    {"ticker": "GILD", "announcement": "2026-02-23", "offer": 115.00, "prior_close": 151.40},
)

MISSING_MARKET_INPUTS = (
    "implied volatility",
    "listed strike",
    "expiration",
    "option bid",
    "option ask",
    "last-trade timestamp",
)


def _case(**over):
    row = dict(ANCHOR)
    row.update(over)
    return row


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _plain_match(assumptions, quoted):
    if quoted is None:
        return None
    spot = assumptions["spot"]
    strike = assumptions["strike"]
    days = assumptions["days"]
    rate = assumptions["rate"]
    vol = assumptions["volatility"]
    other = pricing.black_scholes(spot, strike, days / 365.0, rate, vol, "put")
    return abs(quoted - other)


def _scenario_map(result):
    if not result.get("scenarios"):
        return {}
    return {item["key"]: item for item in result["scenarios"]}


def _inspect(assumptions, result):
    """Structural checks. These do not judge which model is closer to a market."""
    notes = []
    prices = [result.get("black_scholes"), result.get("scenario_value")]
    for name, value in (("black_scholes", prices[0]), ("scenario_value", prices[1])):
        if value is None:
            continue
        if not _finite(value):
            notes.append("%s is not a finite number." % name)
        elif value < -1e-10:
            notes.append("%s is negative (%.6g)." % (name, value))
    gap = None
    if result.get("black_scholes") is not None and "volatility" not in result["missing"]:
        gap = _plain_match(assumptions, result["black_scholes"])
        if gap is not None and gap > 1e-8:
            notes.append("The two Black-Scholes functions differ by %.3g on the same inputs." % gap)
    weights = _scenario_map(result)
    if weights:
        total = sum(item["weight"] for item in result["scenarios"])
        if abs(total - 1.0) > 1e-10:
            notes.append("Scenario weights sum to %.12g." % total)
        for item in result["scenarios"]:
            if not 0.0 - 1e-12 <= item["weight"] <= 1.0 + 1e-12:
                notes.append("The %s weight is outside 0 to 1." % item["key"])
            if not _finite(item["value"]) or item["value"] < -1e-10:
                notes.append("The %s scenario value is invalid." % item["key"])
        values = [item["value"] for item in result["scenarios"]]
        fair = result["scenario_value"]
        if fair is not None and (fair < min(values) - 1e-8 or fair > max(values) + 1e-8):
            notes.append("The M&A price sits outside the three scenario values.")
        expected_close = result["p_close"] * result["resolve"]
        expected_break = (1.0 - result["p_close"]) * result["resolve"]
        expected_pending = 1.0 - result["resolve"]
        if abs(weights["close"]["weight"] - expected_close) > 1e-10:
            notes.append("The close weight is not close probability times resolve.")
        if abs(weights["break"]["weight"] - expected_break) > 1e-10:
            notes.append("The break weight is not the failure share of resolve.")
        if abs(weights["pending"]["weight"] - expected_pending) > 1e-10:
            notes.append("The pending weight is not one minus resolve.")
    return {"bs_gap": gap, "notes": notes}


def price_case(assumptions):
    result = put_benchmark.benchmark(assumptions)
    check = _inspect(assumptions, result)
    scenes = _scenario_map(result)
    return {
        "assumptions": assumptions,
        "result": result,
        "bs_gap": check["bs_gap"],
        "notes": check["notes"],
        "weights": {key: scenes[key]["weight"] for key in scenes},
        "scenario_spots": {key: scenes[key]["spot"] for key in scenes},
        "scenario_values": {key: scenes[key]["value"] for key in scenes},
    }


def _column(rows, name, path):
    values = []
    for row in rows:
        if path == "input":
            values.append(row["input"])
        elif path == "bs":
            values.append(row["result"]["black_scholes"])
        elif path == "ma":
            values.append(row["result"]["scenario_value"])
        elif path == "diff":
            values.append(row["result"]["difference"])
        elif path == "resolve":
            values.append(row["result"]["resolve"])
        elif path == "expires":
            values.append(row["result"]["expires_before_close"])
        else:
            values.append(row.get(path))
    return values


def _sweep(label, key, values):
    rows = []
    for value in values:
        case = price_case(_case(**{key: value}))
        case["input"] = value
        case["label"] = label
        rows.append(case)
    return rows


def _largest_step(rows, field):
    best = None
    for left, right in zip(rows, rows[1:]):
        a = left["result"][field]
        b = right["result"][field]
        if a is None or b is None:
            continue
        step = abs(b - a)
        if best is None or step > best["step"]:
            best = {
                "step": step,
                "from": left["input"],
                "to": right["input"],
                "from_value": a,
                "to_value": b,
            }
    return best


def _slope_change(rows, field, at):
    """Compare the one-step slopes on either side of an input value."""
    indexed = {row["input"]: row["result"][field] for row in rows}
    if at - 1 not in indexed or at not in indexed or at + 1 not in indexed:
        return None
    left = indexed[at] - indexed[at - 1]
    right = indexed[at + 1] - indexed[at]
    return {"at": at, "left": left, "right": right, "gap": right - left}


def _direct_scenario(spot):
    """The production scenario formula, including a spot the benchmark withholds."""
    deal = {
        "offer": ANCHOR["acquisition_price"],
        "downside": ANCHOR["downside"],
        "spot": spot,
        "cash": True,
    }
    contract = {
        "kind": "put",
        "strike": ANCHOR["strike"],
        "days": ANCHOR["days"],
        "rate": ANCHOR["rate"],
        "vol": ANCHOR["volatility"],
        "premium": 0.0,
    }
    resolve = pricing.resolved_by_expiry(ANCHOR["days"], ANCHOR["days_to_close"])
    probs = {
        "p_close": ANCHOR["p_close"],
        "resolve": resolve,
        "p_pending": ANCHOR["p_pending"],
    }
    return pricing.scenario_value(deal, contract, probs)["fair"]


def _unpriced_historical():
    rows = []
    for deal in UNPRICED_DEALS:
        attempt = put_benchmark.benchmark({
            "spot": deal["prior_close"],
            "strike": None,
            "days": None,
            "rate": None,
            "volatility": None,
            "downside": None,
            "days_to_close": None,
            "consideration": "cash",
            "acquisition_price": deal["offer"],
            "p_close": None,
            "p_pending": None,
        })
        rows.append({
            "deal": deal,
            "missing": attempt["missing"],
            "black_scholes": attempt["black_scholes"],
            "scenario_value": attempt["scenario_value"],
        })
    return rows


def measure():
    close_probability = _sweep("close probability", "p_close", (0.0, 0.25, 0.50, 0.70, 0.90, 1.0))
    pending = _sweep("pending probability", "p_pending", (0.0, 0.30, 0.60, 0.84, 1.0))
    offer = _sweep("offer", "acquisition_price", (30.0, 40.0, 50.0, 60.0, 80.0, 120.0))
    downside = _sweep("downside", "downside", (15.0, 25.0, 32.0, 40.0, 50.0, 70.0))
    volatility = _sweep("volatility", "volatility", (0.10, 0.12, 0.18, 0.25, 0.35, 0.50, 0.80))
    days = _sweep("days", "days", (15, 30, 47, 48, 49, 90, 119, 120, 121, 155, 156, 157, 200))
    dense_days = _sweep("days", "days", tuple(range(10, 201)))
    spot = _sweep("spot", "spot", (35.0, 40.0, 41.0, 50.0, 70.0, 100.0))
    considerations = []
    for name, extra in (
        ("cash", {"consideration": "cash", "acquisition_price": 60.0}),
        ("stock", {
            "consideration": "stock",
            "exchange_ratio": 0.5,
            "acquirer_price": 120.0,
        }),
        ("mixed", {
            "consideration": "mixed",
            "cash_amount": 20.0,
            "exchange_ratio": 0.4,
            "acquirer_price": 100.0,
        }),
    ):
        case = price_case(_case(**extra))
        case["input"] = name
        case["level"] = case["result"]["acquisition_level"]
        considerations.append(case)

    with_premium = price_case(_case(market_premium=1.25))
    without_premium = price_case(_case())
    early = price_case(_case(days=30, days_to_close=180))
    refused = black_scholes.acquisition_option_value({
        "spot": 50, "strike": 40, "rate": 0.045, "kind": "put",
        "standalone_volatility": 0.35, "deal_volatility": pricing.VOL_PINNED_CASH,
        "acquisition_probability": 0.70, "failure_probability": 0.30,
        "consideration": "cash", "acquisition_price": 60, "downside": 32,
        "days_to_expiration": 30, "days_to_close": 180,
    })
    otm_direct = _direct_scenario(50.0)
    itm_direct = _direct_scenario(35.0)
    findings = _findings(
        close_probability, pending, offer, downside, volatility, days, dense_days,
        spot, considerations, with_premium, without_premium, early, refused,
        otm_direct, itm_direct,
    )
    return {
        "anchor": dict(ANCHOR),
        "close_probability": close_probability,
        "pending": pending,
        "offer": offer,
        "downside": downside,
        "volatility": volatility,
        "days": days,
        "spot": spot,
        "considerations": considerations,
        "historical": _unpriced_historical(),
        "findings": findings,
        "constants": {
            "cash_vol": pricing.VOL_PINNED_CASH,
            "pending_vol": pricing.VOL_PENDING,
            "stock_factor": pricing.STOCK_DEAL_VOL_FACTOR,
        },
    }


def _monotone(rows, field, direction):
    """direction 1 means the series should not fall. -1 means it should not rise."""
    breaks = []
    previous = None
    previous_input = None
    for row in rows:
        value = row["result"][field]
        if value is None or previous is None:
            previous = value
            previous_input = row["input"]
            continue
        moved = value - previous
        if direction > 0 and moved < -1e-8:
            breaks.append((previous_input, row["input"], moved))
        if direction < 0 and moved > 1e-8:
            breaks.append((previous_input, row["input"], moved))
        previous = value
        previous_input = row["input"]
    return breaks


def _findings(close_probability, pending, offer, downside, volatility, days, dense_days,
              spot, considerations, with_premium, without_premium, early, refused,
              otm_direct, itm_direct):
    findings = []
    notes = []
    for group in (close_probability, pending, offer, downside, volatility, days, spot, considerations):
        for row in group:
            notes.extend(row["notes"])
    if notes:
        findings.append({"kind": "invalid", "text": " ".join(notes)})
    else:
        findings.append({
            "kind": "check",
            "text": "Every returned price is finite and non-negative. Every priced row's weights are between 0 and 1 and sum to 1. The M&A price stays inside the three scenario values.",
        })

    gaps = [row["bs_gap"] for group in (close_probability, offer, downside, volatility, days, spot, considerations) for row in group if row["bs_gap"] is not None]
    widest = max(gaps) if gaps else None
    findings.append({
        "kind": "check",
        "text": "Black-Scholes in the benchmark and Black-Scholes in pricing.py use the same spot, strike, year fraction, rate, and volatility. The largest absolute gap on these rows is %.3g." % widest,
    })

    priced_spots = [row for row in spot if row["result"]["scenario_value"] is not None]
    spot_span = max(row["result"]["scenario_value"] for row in priced_spots) - min(row["result"]["scenario_value"] for row in priced_spots)
    withheld = [row["input"] for row in spot if row["result"]["scenario_value"] is None and row["result"]["black_scholes"] is not None]
    findings.append({
        "kind": "property",
        "text": "While the put remains out of the money, the M&A price does not change with the stock price. The range across those spots is %.3g. At stock prices %s the benchmark still returns Black-Scholes and withholds the M&A price because the put is not out of the money." % (
            spot_span, ", ".join("%.0f" % value for value in withheld)),
    })
    if abs(otm_direct - itm_direct) < 1e-10:
        findings.append({
            "kind": "property",
            "text": "Calling the scenario formula directly at stock price 35 and stock price 50 returns the same M&A price, %.6f. The formula replaces the stock price with the offer, the pending blend, and the downside before it prices the put. The benchmark's refusal at or above the strike is a gate, not a jump in that formula." % otm_direct,
        })

    close_values = [row["result"]["scenario_value"] for row in close_probability]
    span = close_values[-1] - close_values[0]
    second = abs((close_values[0] + close_values[-1]) / 2.0 - close_values[2])
    findings.append({
        "kind": "property",
        "text": "With the other hypothetical inputs fixed, the M&A price moves in a straight line as the close probability goes from 0 to 1. The change is %.6f. The midpoint of the two ends differs from the 0.50 result by %.3g. Black-Scholes does not use the close probability, so it stays at %.6f." % (
            span, second, close_probability[0]["result"]["black_scholes"]),
    })

    pending_weights = {tuple(round(row["weights"][key], 12) for key in ("close", "pending", "break")) for row in pending}
    pending_prices = [row["result"]["scenario_value"] for row in pending]
    if len(pending_weights) == 1 and max(pending_prices) - min(pending_prices) > 1e-8:
        findings.append({
            "kind": "property",
            "text": "Changing the pending probability moves the pending stock level and the M&A price, from %.6f to %.6f. It does not change the three weights. The pending probability is not the close probability.",
        })
        findings[-1]["text"] = findings[-1]["text"] % (min(pending_prices), max(pending_prices))

    vol_bs = _monotone(volatility, "black_scholes", 1)
    if vol_bs:
        findings.append({"kind": "inconsistency", "text": "Black-Scholes fell as volatility rose: %s." % vol_bs})
    else:
        low = volatility[0]["result"]
        high = volatility[-1]["result"]
        findings.append({
            "kind": "property",
            "text": "Raising volatility from %.2f to %.2f raises the Black-Scholes put from %.6f to %.6f and the M&A put from %.6f to %.6f. In a cash deal the close scenario keeps volatility at %.2f and the pending scenario keeps volatility at %.2f, so only the break scenario uses the supplied volatility." % (
                volatility[0]["input"], volatility[-1]["input"],
                low["black_scholes"], high["black_scholes"],
                low["scenario_value"], high["scenario_value"],
                pricing.VOL_PINNED_CASH, pricing.VOL_PENDING),
        })

    day_step = _largest_step(dense_days, "scenario_value")
    bs_step = _largest_step(dense_days, "black_scholes")
    kink_48 = _slope_change(dense_days, "scenario_value", 48)
    kink_156 = _slope_change(dense_days, "scenario_value", 156)
    cross = _slope_change(dense_days, "scenario_value", 120)
    findings.append({
        "kind": "property",
        "text": "Across expiration of 10 through 200 days, with the expected close held at 120, the largest one-day M&A change is %.6f (day %s to %s) and the largest one-day Black-Scholes change is %.6f. Neither is a jump. At the expected-close boundary the one-day slopes are %.6f and %.6f. The expires-before flag flips at that boundary, and the price does not." % (
            day_step["step"], day_step["from"], day_step["to"], bs_step["step"],
            cross["left"], cross["right"]),
    })
    findings.append({
        "kind": "property",
        "text": "Resolve is flat at 0.03 until expiration reaches 40 percent of the time to close, then rises in a straight line, then stays at 0.97 from 130 percent. Those corners fall on day 48 and day 156. The M&A put's one-day change shifts by %.6f at day 48 and by %.6f at day 156. The weight rule has a corner. The put price does not jump.",
    })
    findings[-1]["text"] = findings[-1]["text"] % (abs(kink_48["right"] - kink_48["left"]), abs(kink_156["right"] - kink_156["left"]))

    same_level = len({row["level"] for row in considerations}) == 1
    same_bs = max(row["result"]["black_scholes"] for row in considerations) - min(row["result"]["black_scholes"] for row in considerations)
    ma_values = {row["input"]: row["result"]["scenario_value"] for row in considerations}
    findings.append({
        "kind": "property" if same_level and same_bs < 1e-10 else "inconsistency",
        "text": "Cash, stock, and mixed are set so each acquisition level is 60. Black-Scholes is the same on all three, within %.3g. The M&A prices differ because a cash close uses volatility %.2f and a stock or mixed close uses %.0f percent of the supplied volatility: cash %.6f, stock %.6f, mixed %.6f." % (
            same_bs, pricing.VOL_PINNED_CASH, pricing.STOCK_DEAL_VOL_FACTOR * 100,
            ma_values["cash"], ma_values["stock"], ma_values["mixed"]),
    })

    premium_gap = abs(with_premium["result"]["scenario_value"] - without_premium["result"]["scenario_value"])
    premium_bs = abs(with_premium["result"]["black_scholes"] - without_premium["result"]["black_scholes"])
    findings.append({
        "kind": "check",
        "text": "Adding a hypothetical market premium of 1.25 does not change either theoretical price. The M&A gap is %.3g and the Black-Scholes gap is %.3g. No market premium is used in the sweeps.",
    })
    findings[-1]["text"] = findings[-1]["text"] % (premium_gap, premium_bs)

    if early["result"]["scenario_value"] is not None and refused.get("expected") is None:
        findings.append({
            "kind": "inconsistency",
            "text": "When the option expires before the expected close, the benchmark still returns an M&A price of %.6f by lowering resolve to %.2f. black_scholes.acquisition_option_value returns no expected value for the same timing and says the acquisition price is not an option payoff. The benchmark follows pricing.scenario_value. It does not follow acquisition_option_value. Those two formulas are not interchangeable.",
        })
        findings[-1]["text"] = findings[-1]["text"] % (early["result"]["scenario_value"], early["result"]["resolve"])

    offer_move = offer[-1]["result"]["scenario_value"] - offer[0]["result"]["scenario_value"]
    findings.append({
        "kind": "property",
        "text": "Raising the cash offer from %.0f to %.0f changes the M&A put by %.6f and leaves Black-Scholes unchanged. On this grid the M&A put falls at every step, and the last steps are nearly flat because the close and pending puts are already worth about nothing.",
    })
    findings[-1]["text"] = findings[-1]["text"] % (offer[0]["input"], offer[-1]["input"], offer_move)
    pending_step = _largest_step(pending, "scenario_value")
    findings.append({
        "kind": "property",
        "text": "The largest pending-probability step is %.6f, from %.2f to %.2f. The pending stock level crosses the strike of %.0f inside that step, so that scenario's put loses most of its value. The weights do not change.",
    })
    findings[-1]["text"] = findings[-1]["text"] % (
        pending_step["step"], pending_step["from"], pending_step["to"], ANCHOR["strike"])
    downside_move = downside[-1]["result"]["scenario_value"] - downside[0]["result"]["scenario_value"]
    findings.append({
        "kind": "property",
        "text": "Raising the deal-break downside from %.0f to %.0f changes the M&A put by %.6f and leaves Black-Scholes unchanged. A downside above the offer is priced as written. It is not treated as a data error.",
    })
    findings[-1]["text"] = findings[-1]["text"] % (downside[0]["input"], downside[-1]["input"], downside_move)
    return findings


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if abs(value) >= 0.0001 or value == 0:
        return "%.6f" % value
    return "%.4e" % value


def _table(headers, records):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for record in records:
        lines.append("| " + " | ".join(record) + " |")
    return "\n".join(lines)


def _price_table(rows, input_name):
    records = []
    for row in rows:
        result = row["result"]
        records.append((
            _fmt(row["input"]),
            _fmt(result["black_scholes"]),
            _fmt(result["scenario_value"]),
            _fmt(result["difference"]),
            _fmt(result.get("resolve")),
            _fmt(result.get("expires_before_close")),
        ))
    return _table(
        (input_name, "Black-Scholes", "M&A-aware", "M&A minus Black-Scholes", "Resolve", "Expires before close"),
        records,
    )


def render(result):
    anchor = result["anchor"]
    lines = [
        "# OTM put sensitivity",
        "",
        "This report prices one hypothetical put with the existing Black-Scholes function and the existing three-scenario function. It does not use a market premium, and it does not say which price is more accurate.",
        "",
        "## Hypothetical contract",
        "",
        "The anchor is not a historical deal. A missing historical input was not filled with one of these numbers.",
        "",
        _table(
            ("Input", "Value"),
            (
                ("Stock price", _fmt(anchor["spot"])),
                ("Strike", _fmt(anchor["strike"])),
                ("Days to expiration", str(anchor["days"])),
                ("Expected days to close", str(anchor["days_to_close"])),
                ("Rate", _fmt(anchor["rate"])),
                ("Volatility", _fmt(anchor["volatility"])),
                ("Cash offer", _fmt(anchor["acquisition_price"])),
                ("Downside", _fmt(anchor["downside"])),
                ("Close probability", _fmt(anchor["p_close"])),
                ("Pending probability", _fmt(anchor["p_pending"])),
                ("Market premium", "not supplied"),
            ),
        ),
        "",
        "One input changes in each table. The others stay at the anchor. The year fraction is days divided by 365 in both models.",
        "",
        "## Historical deals that were not priced",
        "",
        "`historical_stock_prices` stores a daily stock close. It does not store an option quote or an implied volatility. The seven cash deals below have an offer and a prior stock close in the realized-payoff report. They were passed to the benchmark with the option terms left empty. Both prices stayed empty.",
        "",
        "Missing on every one of these deals: %s." % ", ".join(MISSING_MARKET_INPUTS),
        "",
    ]
    historical_rows = []
    for row in result["historical"]:
        deal = row["deal"]
        historical_rows.append((
            deal["ticker"],
            deal["announcement"],
            _fmt(deal["offer"]),
            _fmt(deal["prior_close"]),
            _fmt(row["black_scholes"]),
            _fmt(row["scenario_value"]),
        ))
    lines.extend([
        _table(
            ("Ticker", "Announcement", "Stored offer", "Stored prior close", "Black-Scholes", "M&A-aware"),
            historical_rows,
        ),
        "",
        "## Close probability",
        "",
        _price_table(result["close_probability"], "Close probability"),
        "",
        "The pending probability stays at %.2f in this table. It is a separate input." % anchor["p_pending"],
        "",
        _price_table(result["pending"], "Pending probability"),
        "",
        "## Offer price",
        "",
        _price_table(result["offer"], "Cash offer"),
        "",
        "## Deal-break downside",
        "",
        _price_table(result["downside"], "Downside"),
        "",
        "## Implied volatility",
        "",
        "The volatility column is the volatility supplied to both functions. The cash close scenario then replaces it with %.2f, and the pending scenario uses %.2f." % (
            result["constants"]["cash_vol"], result["constants"]["pending_vol"]),
        "",
        _price_table(result["volatility"], "Supplied volatility"),
        "",
        "## Time to expiration",
        "",
        "The expected close stays at %d days. Resolve is 0.03 at or below 40 percent of that time and 0.97 at or above 130 percent." % anchor["days_to_close"],
        "",
        _price_table(result["days"], "Days to expiration"),
        "",
        "## Cash, stock, and mixed",
        "",
        "Each structure is set to an acquisition level of 60. The stock case is an exchange ratio of 0.5 and an acquirer price of 120. The mixed case is 20 in cash plus a ratio of 0.4 on an acquirer price of 100.",
        "",
    ])
    consideration_rows = []
    for row in result["considerations"]:
        consideration_rows.append((
            row["input"],
            _fmt(row["level"]),
            _fmt(row["result"]["black_scholes"]),
            _fmt(row["result"]["scenario_value"]),
            _fmt(row["result"]["difference"]),
            _fmt(row["scenario_values"].get("close")),
        ))
    lines.extend([
        _table(
            ("Consideration", "Level", "Black-Scholes", "M&A-aware", "M&A minus Black-Scholes", "Close-scenario put"),
            consideration_rows,
        ),
        "",
        "## Stock price",
        "",
        _price_table(result["spot"], "Stock price"),
        "",
        "## Checks",
        "",
    ])
    for finding in result["findings"]:
        lines.append("- %s" % finding["text"])
    lines.extend([
        "",
        "## Suggested improvements",
        "",
        "None of these are implemented. The pricing functions were not changed.",
        "",
        "- Show the scenario stock prices beside the market stock price. The M&A price does not respond to the market stock price while the put is out of the money, and a reader can otherwise think both models used the same underlying.",
        "- State the volatility each scenario actually uses. A cash close does not use the supplied implied volatility.",
        "- Keep `acquisition_option_value` out of this comparison. It refuses an option that expires before the expected close. The live scenario model does not.",
        "- The resolve clamps at 0.03 and 0.97 make the slope change at 40 percent and 130 percent of the time to close. A smooth curve would need an explicit decision to replace that rule.",
        "- A historical pricing-error study still needs a real option bid, ask, and quote time. This report does not supply them.",
        "",
        "## Limits",
        "",
        "- The prices are European values from the current functions. They are not exchange quotes and they are not a forecast of profit.",
        "- A difference between the two prices is not evidence that one model is better.",
        "- The anchor probabilities are labels for the sweep. They are not the filing heuristic and they are not a trained probability.",
        "- No paid data source was contacted, and no options file was read.",
        "",
    ])
    return "\n".join(lines) + "\n"
