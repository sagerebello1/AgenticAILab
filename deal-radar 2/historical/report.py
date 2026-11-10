"""Readiness is decided from measured counts. A large row count is not completeness."""


def judge(stats):
    """Whether each dataset can support a later training run. This does not train anything.

    A count above a minimum is not treated as a complete dataset.
    """
    notes = []
    usable = all(stats.get(key, 0) >= 100 for key in ("usable_30", "usable_90", "usable_180"))
    positives = all(stats.get("positives_%d" % days, 0) >= 20 for days in (30, 90, 180))
    negatives = all(stats.get("negatives_%d" % days, 0) >= 20 for days in (30, 90, 180))
    if stats.get("lookahead_violations", 0):
        notes.append("At least one snapshot uses a price or filing from after its cutoff.")
    if stats.get("unread_hits", 0) > stats.get("verified_transactions", 0):
        notes.append("Most item 1.01 search hits were not read. The transaction list is a sample, not the full set of filings.")
    if stats.get("positives_180", 0) > max(1, stats.get("verified_transactions", 0)):
        notes.append("The 30, 90, and 180 day rows repeat the same announced deals. They are not separate companies.")
    if stats.get("non_acquired_companies", 0) < 100:
        notes.append("Non-acquired companies are a small control group, not a market-wide sample.")
    acquisition = (
        usable and positives and negatives
        and stats.get("lookahead_violations", 0) == 0
        and stats.get("unread_hits", 0) <= stats.get("verified_transactions", 0)
        and stats.get("non_acquired_companies", 0) >= 100
    )
    if not acquisition and not notes:
        notes.append("Acquisition snapshots do not yet have 100 usable rows and 20 positives and 20 negatives at each horizon.")

    premiums = stats.get("premiums", 0)
    price_ready = (
        stats.get("event_deals", 0) >= 40
        and premiums >= 40
        and stats.get("lookahead_violations", 0) == 0
    )
    if stats.get("event_deals", 0) and premiums < 40:
        notes.append(
            "%d deals have a market close before and after the announcement. Only %d also have a cash offer, so an offer-to-market comparison is not supported yet."
            % (stats.get("event_deals", 0), premiums)
        )
    elif not price_ready:
        notes.append("Post-announcement prices are missing for too many verified deals to train a price model.")

    labeled = stats.get("closed", 0) + stats.get("terminated", 0)
    unresolved = stats.get("unresolved", 0)
    close_ready = (
        labeled >= 40
        and stats.get("terminated", 0) >= 8
        and unresolved <= labeled
        and stats.get("lookahead_violations", 0) == 0
    )
    if labeled and unresolved > labeled:
        notes.append(
            "%d deals have a closing or termination sentence. %d do not, so the outcome label is missing for most transactions."
            % (labeled, unresolved)
        )
    elif not close_ready:
        notes.append("Closed and terminated outcomes are too few to train a closing model.")
    return {
        "acquisition": acquisition,
        "post_announcement_price": price_ready,
        "deal_completion": close_ready,
        "trained": False,
        "notes": notes,
    }


def render_markdown(stats, judgment, limitations):
    lines = [
        "# Historical data readiness",
        "",
        "Generated %s. No model was trained in this run." % stats.get("generatedAt"),
        "",
        "## Counts",
        "",
        "- Search hits stored: %d" % stats.get("search_hits", 0),
        "- Filings read: %d" % stats.get("filings_read", 0),
        "- Verified target transactions, after dropping amendments and same-week duplicates: %d" % stats.get("verified_transactions", 0),
        "- Buyer filings read and excluded from that count: %d" % stats.get("buyer_filings", 0),
        "- Unclear or not a merger after reading: %d" % stats.get("not_verified_roles", 0),
        "- Competing-offer links: %d" % stats.get("competing_links", 0),
        "- Closed, from a later filing sentence: %d" % stats.get("closed", 0),
        "- Terminated, from a later filing sentence: %d" % stats.get("terminated", 0),
        "- Unresolved transactions: %d" % stats.get("unresolved", 0),
        "- Non-acquired company snapshots: %d" % stats.get("non_acquired_companies", 0),
        "- Tickers with at least one stored price bar: %d of %d requested" % (
            stats.get("tickers_with_prices", 0), stats.get("tickers_requested", 0)),
        "- Usable 30-day observations: %d (positives %d, negatives %d)" % (
            stats.get("usable_30", 0), stats.get("positives_30", 0), stats.get("negatives_30", 0)),
        "- Usable 90-day observations: %d (positives %d, negatives %d)" % (
            stats.get("usable_90", 0), stats.get("positives_90", 0), stats.get("negatives_90", 0)),
        "- Usable 180-day observations: %d (positives %d, negatives %d)" % (
            stats.get("usable_180", 0), stats.get("positives_180", 0), stats.get("negatives_180", 0)),
        "- Verified deals with a pre-announcement close and a later market close: %d" % stats.get("event_deals", 0),
        "- Market close one session before announcement: %d" % stats.get("price_before", 0),
        "- Market close on the announcement session: %d" % stats.get("price_day0", 0),
        "- Market close one session after: %d" % stats.get("price_day1", 0),
        "- Market close five sessions after: %d" % stats.get("price_day5", 0),
        "- Market close ten sessions after: %d" % stats.get("price_day10", 0),
        "- Market close thirty sessions after: %d" % stats.get("price_day30", 0),
        "- Observed premium, only where both the cash offer and the pre-close exist: %d" % stats.get("premiums", 0),
        "- News rows: %d" % stats.get("news_rows", 0),
        "- Look-ahead violations: %d" % stats.get("lookahead_violations", 0),
        "",
        "## Missing fields among verified transactions",
        "",
    ]
    for name, count in stats.get("missing_fields", []):
        lines.append("- %s: %d" % (name, count))
    lines.extend(["", "## Provider limits", ""])
    for item in limitations:
        lines.append("- %s" % item)
    lines.extend(["", "## Ready for a later training run", ""])
    for name in ("acquisition", "post_announcement_price", "deal_completion"):
        lines.append("- %s: %s" % (name, "yes" if judgment[name] else "no"))
    lines.append("- A model was trained: no")
    lines.extend(["", "## Why a row count is not completeness", ""])
    for note in judgment["notes"]:
        lines.append("- %s" % note)
    if not judgment["notes"]:
        lines.append("- The count gates are met. The sample is still a case-control extract from SEC phrase search, not the full population of companies.")
    lines.append("")
    return "\n".join(lines)
