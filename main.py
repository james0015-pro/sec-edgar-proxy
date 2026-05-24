"""SEC EDGAR Insider Trading Proxy API
Deployed on US-based server (Hetzner Virginia).
Uses SEC submissions API for reliable data + Archives for document detail.

Endpoints:
  GET /insider/ticker?ticker=AAPL&lookback=90  — insider trades by ticker
  GET /insider/cik?cik=320193&lookback=90       — insider trades by CIK
  GET /filing?acc=0001140361-26-020871&cik=320193 — Form 4 XML detail
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="SEC EDGAR Proxy", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "MyCompany james0015@proton.me",
    "Accept": "application/json",
}


def cik_from_ticker(ticker: str) -> str:
    """Resolve ticker to CIK using SEC company_tickers.json."""
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        company_data = json.loads(resp.read())

    ticker_upper = ticker.upper()
    for _, info in company_data.items():
        if info.get("ticker", "").upper() == ticker_upper:
            return str(info["cik_str"])

    raise HTTPException(status_code=404, detail=f"Ticker not found: {ticker}")


def cik_padded(cik: str) -> str:
    """Pad CIK to 10 digits for SEC API URLs."""
    return cik.zfill(10)


def fetch_insider_trades(cik: str, lookback_days: int = 90) -> list:
    """
    Fetch Form 4 filings from SEC submissions API.
    Returns recent Form 4 filings within lookback window.
    """
    padded = cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise HTTPException(status_code=502, detail=f"SEC API HTTP {e.code}: {body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    filings = data.get("filings", {}).get("recent", {})
    if not filings:
        return []

    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    acc_numbers = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    report_dates = filings.get("reportDate", [])

    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    trades = []

    for i in range(len(forms)):
        if forms[i] != "4":
            continue

        # Parse date
        try:
            file_date = datetime.strptime(dates[i], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue

        if file_date < cutoff_date:
            continue

        acc = acc_numbers[i] if i < len(acc_numbers) else ""
        primary = primary_docs[i] if i < len(primary_docs) else ""

        trades.append(
            {
                "filing_date": dates[i] if i < len(dates) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "accession_number": acc,
                "form_type": "4",
                "primary_document": primary,
                "form_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{acc.replace('-', '')}/{primary}"
                ) if acc and primary else "",
            }
        )

    return trades


def parse_form4_xml(xml_text: str, cik: str) -> dict:
    """Parse Form 4 XML and extract transaction details."""
    ns = {
        "ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable",
        "n": "http://www.sec.gov/edgar/common_doc",
    }

    root = ET.fromstring(xml_text)

    # Try multiple namespace approaches
    transactions = []

    # Find all nonDerivativeTransaction and derivativeTransaction
    for tag in [
        "nonDerivativeTransaction",
        "derivativeTransaction",
        "{http://www.sec.gov/edgar/common_doc}nonDerivativeTransaction",
        "{http://www.sec.gov/edgar/common_doc}derivativeTransaction",
    ]:
        for tx in root.iter(tag):
            tx_data = {}
            for child in tx:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                tx_data[tag_name] = child.text or ""
            transactions.append(tx_data)

    # Find reporting owner
    owner = {}
    for owner_tag in [
        "reportingOwner",
        "{http://www.sec.gov/edgar/common_doc}reportingOwner",
    ]:
        for rp in root.iter(owner_tag):
            for child in rp:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                owner[tag_name] = child.text or ""

    return {
        "owner": owner,
        "transactions": transactions,
    }


@app.get("/")
def root():
    return {"service": "SEC EDGAR Proxy", "status": "running", "version": "2.0.0"}


@app.get("/insider/ticker")
def insider_by_ticker(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL, TSLA)"),
    lookback: int = Query(90, description="Lookback days (default 90)"),
):
    """Get Form 4 insider trading filings by ticker."""
    cik = cik_from_ticker(ticker)
    trades = fetch_insider_trades(cik, lookback)
    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "filings": trades,
        "count": len(trades),
        "lookback_days": lookback,
    }


@app.get("/insider/cik")
def insider_by_cik(
    cik: str = Query(..., description="CIK number (e.g. 320193 for AAPL)"),
    lookback: int = Query(90, description="Lookback days (default 90)"),
):
    """Get Form 4 insider trading filings by CIK."""
    trades = fetch_insider_trades(cik, lookback)
    return {
        "cik": cik,
        "filings": trades,
        "count": len(trades),
        "lookback_days": lookback,
    }


@app.get("/filing")
def filing_detail(
    acc: str = Query(..., description="Accession number with dashes (e.g. 0001140361-26-020871)"),
    cik: str = Query(..., description="Company CIK number"),
):
    """
    Fetch and parse a specific Form 4 filing from SEC Archives.
    Returns structured transaction data from the XML.
    """
    padded = cik_padded(cik)
    acc_no_dash = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dash}/{acc_no_dash}.txt"

    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "text/html,application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise HTTPException(
                status_code=502,
                detail="SEC Archives blocked this request (geo-restriction). Make sure proxy is deployed on US server.",
            )
        raise HTTPException(status_code=502, detail=f"SEC HTTP {e.code}")

    # Find the XML document reference
    # Look for <xml> or <XML> references
    result = {
        "accession_number": acc,
        "cik": cik,
        "raw_url": url,
        "parsed": None,
    }

    # Try to find and parse the XML portion
    # Form 4 filings contain both the cover page and the XML inside the .txt
    xml_start = raw.find("<XML>")
    if xml_start == -1:
        xml_start = raw.find("<xml>")
    xml_end = raw.find("</XML>")
    if xml_end == -1:
        xml_end = raw.find("</xml>")

    if xml_start != -1 and xml_end != -1:
        xml_content = raw[xml_start + 5 : xml_end]
        try:
            parsed = parse_form4_xml(xml_content, cik)
            result["parsed"] = parsed
            result["status"] = "parsed"
        except ET.ParseError as e:
            result["status"] = "xml_parse_error"
            result["error"] = str(e)[:500]
    else:
        result["status"] = "no_xml_found"
        result["preview"] = raw[:1000]

    return result


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
