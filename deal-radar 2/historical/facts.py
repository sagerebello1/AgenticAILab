"""Point-in-time figures from SEC companyfacts. A fact filed after the cutoff is ignored."""
REVENUE_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
)
STATEMENT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def _rows(facts, namespace, tag, unit):
    try:
        return facts["facts"][namespace][tag]["units"][unit]
    except (KeyError, TypeError):
        return []


def select_fact(rows, cutoff):
    """Latest figure whose SEC filed date is on or before the cutoff."""
    usable = []
    for row in rows or []:
        filed = row.get("filed")
        if not filed or filed > cutoff:
            continue
        form = row.get("form")
        if form not in STATEMENT_FORMS:
            continue
        if row.get("val") is None:
            continue
        usable.append(row)
    if not usable:
        return None
    usable.sort(key=lambda row: (row.get("filed") or "", row.get("end") or ""))
    chosen = usable[-1]
    return {
        "value": chosen.get("val"),
        "filed": chosen.get("filed"),
        "form": chosen.get("form"),
        "end": chosen.get("end"),
        "accn": chosen.get("accn"),
    }


def select_tag(facts, tags, cutoff, namespace="us-gaap", unit="USD"):
    for tag in tags:
        chosen = select_fact(_rows(facts, namespace, tag, unit), cutoff)
        if chosen:
            chosen["tag"] = tag
            return chosen
    return None


def statement_facts(facts, cutoff):
    """Revenue, assets, cash, equity, debt, and shares known on the cutoff. Missing stays None."""
    specs = {
        "revenue": (REVENUE_TAGS, "us-gaap", "USD"),
        "assets": (("Assets",), "us-gaap", "USD"),
        "cash": (("CashAndCashEquivalentsAtCarryingValue", "Cash"), "us-gaap", "USD"),
        "equity": (("StockholdersEquity",), "us-gaap", "USD"),
        "debt": (("LongTermDebtNoncurrent", "LongTermDebt"), "us-gaap", "USD"),
        "shares": (("EntityCommonStockSharesOutstanding",), "dei", "shares"),
    }
    out = {}
    for name, (tags, namespace, unit) in specs.items():
        out[name] = select_tag(facts, tags, cutoff, namespace, unit)
    return out
