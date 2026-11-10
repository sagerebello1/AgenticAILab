"""Deterministic SEC brief: facts in the primary document, not inferred deal odds."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET
import terms

def revenue(raw, period, annual, cik):
    try:
        root=ET.fromstring(raw)
        end=date.fromisoformat(period)
    except (ET.ParseError, ValueError, TypeError):
        return None
    ctx={}
    for c in root.findall(".//{*}context"):
        a,b=c.findtext(".//{*}startDate"),c.findtext(".//{*}endDate")
        identity=c.findtext(".//{*}identifier") or ""
        if not a or not b or not identity.isdigit() or int(identity)!=cik or any(c.find(".//{*}"+tag) is not None for tag in ("segment","scenario")): continue
        start,stop=date.fromisoformat(a),date.fromisoformat(b)
        if (330 <= (stop-start).days <= 380 if annual else 75 <= (stop-start).days <= 105): ctx[c.get("id")]=stop
    units={u.get("id") for u in root.findall(".//{*}unit") if (u.findtext("{*}measure") or "").split(":")[-1]=="USD"}
    vals={}
    for f in root.findall(".//{*}nonFraction"):
        name=f.get("name","")
        if name not in ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax","us-gaap:Revenues","us-gaap:SalesRevenueNet") or f.get("unitRef") not in units or f.get("contextRef") not in ctx:continue
        fmt=f.get("format","").lower()
        if fmt and "dot-decimal" not in fmt:continue
        try:
            v=Decimal("".join(f.itertext()).strip().replace(",",""))*(10**int(f.get("scale","0")))
            if f.get("sign")=="-":v=-v
            if v<0 or not v.is_finite():continue
        except (InvalidOperation,ValueError,TypeError):continue
        vals.setdefault(name,{})[ctx[f.get("contextRef")]]=v
    for series in vals.values():
        if end not in series:continue
        dollars=lambda v: f"${v/Decimal(1000000):,.1f} million" if v>=1000000 else f"${v:,.0f}"
        s=f"For the {'year' if annual else 'quarter'} ending {end.isoformat()}, the company reported {dollars(series[end])} in revenue"
        prior=next((v for dt,v in series.items() if 355<=(end-dt).days<=375),None)
        return s+(f", compared with {dollars(prior)} a year earlier." if prior is not None else ".")
    return None

ITEMS={"1.01":"entering a material agreement","1.02":"ending a material agreement","2.01":"the completion of an acquisition or asset sale","2.02":"financial results","5.02":"changes involving executives or directors","5.07":"a shareholder vote","7.01":"a public investor update","8.01":"another significant event","9.01":"financial statements or supporting exhibits"}
NAMES={"10-Q":"Quarterly financial report","10-K":"Annual financial report","8-K":"Company event report","SC TO-T":"Tender offer filing","4":"Insider ownership report"}
def describe(form):
    return NAMES.get(form.removesuffix("/A"),form)+(" amendment" if form.endswith("/A") else "")

def summarize(raw, f, cik, issuer="The company"):
    form=f["form"]; base=form.removesuffix("/A"); amendment=form.endswith("/A")
    html=raw.decode("utf-8",errors="replace")
    clean=re.sub(r'(?is)<ix:header\b.*?</ix:header>|<table\b.*?</table>', ' ', html)
    body=terms.to_text(clean)
    what=None
    if base in ("10-Q","10-K") and not amendment:
        what=revenue(raw,f["period"],base=="10-K",cik)
    tags=[ITEMS[t] for t in re.findall(r"\d\.\d{2}",f["items"]) if t in ITEMS]
    if not what and base=="8-K" and tags:
        what=("The company amended a previous report covering " if amendment else "The company filed an update covering ")+", ".join(tags)+"."
    if not what:
        what=("This filing amends an earlier report. Check the original and amendment to see what changed." if amendment else "The company filed "+describe(form).lower()+(" for the period ending "+f["period"] if f["period"] else "")+". No specific result could be verified automatically from this document.")
    rx=r'\b(?:entered into (?:an? |the )?(?:(?:definitive|amended) )?(?:agreement and plan of merger|merger agreement)|completed (?:its |the )acquisition of|terminated (?:the |its )merger agreement)\b'
    hits=re.search(rx,body,re.I)
    if hits:
        a=max(body.rfind(". ",max(0,hits.start()-110),hits.start())+2,hits.start()-100,0);b=body.find(". ",hits.end(),hits.end()+230)
        evidence=body[a:(b+1 if b!=-1 else hits.end()+160)].strip()
        relation="The filing references a merger agreement or acquisition."
        completed=re.search(r'\bOn ([A-Z][a-z]+ \d{1,2}, \d{4}),? (?:we|the Company) completed (?:the |our )?acquisition of ([^();“”]{2,140}?)(?=\s*\(|, acquiring|, for |\.\s)', body, re.I)
        if completed:
            when,target=completed.groups()
            relation=f"{issuer} completed its acquisition of {target.rstrip('., ')} on {when}."
            evidence=completed.group(0)
    elif base.startswith("SC TO"):
        evidence="";relation="The filing concerns a tender offer."
    elif "2.01" in f["items"] and base=="8-K":
        evidence="";relation="The filing reports an acquisition or disposal of assets under Item 2.01."
    else:
        evidence="";relation=None
    return dict(what=what,relation=relation,evidence=evidence)
