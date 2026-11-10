"""Made-up announced deals, used when EDGAR is not configured or not reachable.

The companies, prices and contracts are fictional. Close odds and their drivers are produced by
the same rules (terms.estimate_probabilities) that score real filings, so the sample behaves
like the live path.
"""
from terms import estimate_probabilities

_SPECS = [
    dict(id="s1", target="Marrow Therapeutics", ticker="MARR", acquirer="Halcyon Biologics", filedDaysAgo=6,
         offer=48.00, consideration="cash", daysToClose=120,
         closePhrase="expected to close in the first quarter of 2027",
         flags=dict(hsr=True, secondRequest=False, foreign=[], other=[], financingCondition=False, tender=False, vote=True,
                    goShop=False, termFees=["$92 million (3.1%)"]),
         market=dict(spot=46.10, downside=34.00),
         contract=dict(kind="call", strike=45.0, days=75, vol=0.38, premium=2.10),
         dealroom=None,
         note="All cash. The two companies make different drugs, so antitrust overlap is small."),
    dict(id="s2", target="Quill Software", ticker="QUIL", acquirer="Northbeam Systems", filedDaysAgo=11,
         offer=27.50, consideration="cash", daysToClose=150,
         closePhrase="expected to close in the second quarter of 2027",
         flags=dict(hsr=True, secondRequest=True, foreign=[], other=[], financingCondition=False, tender=False, vote=True,
                    goShop=False, termFees=["$61 million (2.6%)"]),
         market=dict(spot=26.20, downside=19.50),
         contract=dict(kind="call", strike=27.0, days=210, vol=0.42, premium=1.80),
         dealroom=dict(name="Quill Software", tagline="Workflow tools for enterprise teams", hq="Austin, United States",
                       sectors=["Enterprise software", "Productivity"], valuation=1_900_000_000, valuationYear=2023,
                       fundingTotal=410_000_000, employees=1450, status="operational", url=None),
         note="Second request from antitrust regulators. The two companies compete in enterprise tools."),
    dict(id="s3", target="Lathe Analog", ticker="LATH", acquirer="Corvid Semiconductor", filedDaysAgo=3,
         offer=62.00, consideration="cash", daysToClose=270,
         closePhrase="expected to close by the end of 2027",
         flags=dict(hsr=True, secondRequest=True, foreign=["CFIUS", "China SAMR", "European Commission"], other=[],
                    financingCondition=False, tender=False, vote=True, goShop=False, termFees=["$310 million (4.4%)"]),
         market=dict(spot=54.00, downside=44.00),
         contract=dict(kind="call", strike=55.0, days=120, vol=0.55, premium=3.40),
         dealroom=dict(name="Lathe Analog", tagline="Precision analog chips for industrial equipment", hq="Boston, United States",
                       sectors=["Semiconductors", "Industrial technology"], valuation=6_200_000_000, valuationYear=2024,
                       fundingTotal=880_000_000, employees=3100, status="operational", url=None),
         note="Needs approval in the US, China and the EU. The longest and riskiest path of the five."),
    dict(id="s4", target="Altamar Gas", ticker="ALTA", acquirer="Pinecrest Energy", filedDaysAgo=15,
         offer=41.00, consideration="cash", daysToClose=200,
         closePhrase="expected to close in the third quarter of 2027",
         flags=dict(hsr=True, secondRequest=True, foreign=[], other=["State utility commission"], financingCondition=True,
                    tender=False, vote=True, goShop=False, termFees=["$140 million (3.5%)"]),
         market=dict(spot=39.50, downside=30.00),
         contract=dict(kind="put", strike=37.0, days=300, vol=0.36, premium=1.70),
         dealroom=None,
         note="Depends on debt financing and a state utility commission. A put pays if the deal breaks."),
    dict(id="s5", target="Basil & Rye", ticker="BASI", acquirer="Fernhill Foods", filedDaysAgo=2,
         offer=18.00, consideration="cash", daysToClose=60,
         closePhrase="expected to close in the first quarter of 2027",
         flags=dict(hsr=True, secondRequest=False, foreign=[], other=[], financingCondition=False, tender=True, vote=False,
                    goShop=False, termFees=["$9 million (3.0%)"]),
         market=dict(spot=17.75, downside=13.00),
         contract=dict(kind="call", strike=17.5, days=90, vol=0.30, premium=1.00),
         dealroom=dict(name="Basil & Rye", tagline="Regional grocery and prepared foods", hq="Portland, United States",
                       sectors=["Food and beverage", "Retail"], valuation=None, valuationYear=None,
                       fundingTotal=None, employees=2200, status="operational", url=None),
         note="Small cash tender offer. It should close fast, and the spread is thin."),
]


def sample_deals():
    deals = []
    for s in _SPECS:
        p_close, p_pending, drivers = estimate_probabilities(s["consideration"], s["flags"])
        d = dict(s)
        d.update(source="sample", form="8-K", items=["1.01"], indexUrl=None, docUrl=None, evidence={},
                 pClose=p_close, pPending=p_pending, drivers=drivers, extraction="sample", expectedClose=None)
        d["market"] = dict(s["market"], assumed=False)
        d["contract"] = dict(s["contract"], rate=0.045, assumed=False)
        deals.append(d)
    return deals


if __name__ == "__main__":
    import json
    print(json.dumps(sample_deals()[0], indent=2)[:1500])
