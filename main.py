"""SEC EDGAR + Yahoo Finance Proxy API
Deployed on US-based server (Hetzner Virginia).

Endpoints:
  GET /insider/ticker?ticker=AAPL&lookback=90       — insider Form 4 filings
  GET /insider/cik?cik=320193&lookback=90            — insider by CIK
  GET /institutional/ticker?ticker=AAPL              — 13F filings list
  GET /institutional/search?ticker=AAPL           — 13F reverse search (who holds this stock)
  GET /institutional/nasdaq?ticker=AAPL           — NASDAQ institutional ownership %
  GET /earnings?ticker=AAPL&quarters=8               — earnings history
  GET /price?ticker=AAPL&date=2026-04-27             — price on a date
  GET /filing?acc=...&cik=...                        — Form 4 XML detail
"""

import json
import urllib.request
from datetime import datetime, timedelta

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="SEC + Yahoo Proxy", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "MyCompany james0015@proton.me"}

# ═══════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════


def cik_from_ticker(ticker: str) -> str:
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    tu = ticker.upper()
    for _, info in data.items():
        if info.get("ticker", "").upper() == tu:
            return str(info["cik_str"])
    raise HTTPException(404, detail=f"Ticker not found: {ticker}")


def cik_padded(cik: str) -> str:
    return cik.zfill(10)


def yahoo_price(ticker: str, date_str: str) -> dict:
    """Get OHLCV for a specific date from Yahoo Finance chart API."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, detail=f"Invalid date: {date_str}")

    # Fetch a window around the date (±3 days for weekends/holidays)
    import time

    start_ts = int((dt - timedelta(days=5)).timestamp())
    end_ts = int((dt + timedelta(days=5)).timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    result = data.get("chart", {}).get("result", [{}])[0]
    timestamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]

    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])
    closes = quotes.get("close", [])
    volumes = quotes.get("volume", [])

    target_ts = int(dt.timestamp())
    for i, ts in enumerate(timestamps):
        # Allow ±24h match (market open vs calendar date)
        if abs(ts - target_ts) < 86400 and closes[i] is not None:
            prev_close = closes[i - 1] if i > 0 and closes[i - 1] else opens[i]
            change_pct = (
                ((closes[i] - prev_close) / prev_close * 100)
                if prev_close and prev_close > 0
                else 0
            )
            from datetime import datetime as dt2

            return {
                "date": dt2.fromtimestamp(ts).strftime("%Y-%m-%d"),
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "prev_close": prev_close,
                "change_pct": round(change_pct, 2),
            }

    return {"date": date_str, "error": "No price data for this date (weekend/holiday?)"}


# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════


@app.get("/")
def root():
    return {"service": "SEC + Yahoo Proxy", "version": "2.1.0"}


@app.get("/insider/ticker")
def insider_by_ticker(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    lookback: int = Query(90, description="Lookback days"),
):
    cik = cik_from_ticker(ticker)
    padded = cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])
    rdates = filings.get("reportDate", [])

    cutoff = datetime.now() - timedelta(days=lookback)
    trades = []
    for i in range(len(forms)):
        if forms[i] != "4":
            continue
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
        if fd < cutoff:
            continue
        acc = accs[i] if i < len(accs) else ""
        doc = docs[i] if i < len(docs) else ""
        trades.append(
            {
                "filing_date": dates[i],
                "report_date": rdates[i] if i < len(rdates) else "",
                "accession_number": acc,
                "form_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{acc.replace('-', '')}/{doc}"
                ) if acc and doc else "",
            }
        )

    return {"ticker": ticker.upper(), "cik": cik, "filings": trades, "count": len(trades)}


@app.get("/insider/cik")
def insider_by_cik(
    cik: str = Query(...),
    lookback: int = Query(90),
):
    padded = cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])

    cutoff = datetime.now() - timedelta(days=lookback)
    trades = []
    for i in range(len(forms)):
        if forms[i] != "4":
            continue
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
        if fd < cutoff:
            continue
        acc = accs[i] if i < len(accs) else ""
        doc = docs[i] if i < len(docs) else ""
        trades.append(
            {
                "filing_date": dates[i],
                "accession_number": acc,
                "form_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{acc.replace('-', '')}/{doc}"
                ) if acc and doc else "",
            }
        )

    return {"cik": cik, "filings": trades, "count": len(trades)}


@app.get("/earnings")
def earnings(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    quarters: int = Query(8, description="Number of quarters to return"),
):
    """
    Get earnings dates + estimates + surprises using yfinance.
    Requires yfinance installed on server.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(
            500,
            detail="yfinance not installed. Add 'yfinance' to requirements.txt and redeploy.",
        )

    stock = yf.Ticker(ticker)
    try:
        earnings_data = stock.earnings_dates
    except Exception:
        raise HTTPException(500, detail=f"Failed to fetch earnings for {ticker}")

    if earnings_data is None or earnings_data.empty:
        return {"ticker": ticker.upper(), "earnings": [], "count": 0, "note": "No earnings data available"}

    results = []
    for idx, row in earnings_data.head(quarters * 2).iterrows():
        # idx is the earnings date
        if isinstance(idx, datetime):
            edate = idx.strftime("%Y-%m-%d")
        else:
            edate = str(idx)[:10]

        try:
            surprise = float(row.get("Surprise(%)", 0) or 0)
        except (ValueError, TypeError):
            surprise = 0

        results.append(
            {
                "earnings_date": edate,
                "eps_estimate": row.get("EPS Estimate"),
                "eps_actual": row.get("Reported EPS"),
                "surprise_pct": round(surprise, 2),
            }
        )

    return {"ticker": ticker.upper(), "earnings": results, "count": len(results)}


@app.get("/price")
def stock_price(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
):
    """Get stock price on a specific date."""
    return {"ticker": ticker.upper(), **yahoo_price(ticker, date)}


@app.get("/compare")
def compare(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    quarters: int = Query(8, description="Number of quarters to compare"),
):
    """
    Comprehensive comparison:
    - Earnings dates + price changes on earnings day
    - Insider filing activity around earnings
    - Returns structured data for n8n analysis
    """
    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(500, detail="yfinance not installed")

    cik = cik_from_ticker(ticker)
    stock = yf.Ticker(ticker)

    # 1. Get earnings dates
    try:
        earnings_data = stock.earnings_dates
    except Exception:
        earnings_data = None

    earnings_list = []
    if earnings_data is not None and not earnings_data.empty:
        for idx, row in earnings_data.head(quarters * 2).iterrows():
            if isinstance(idx, datetime):
                edate = idx.strftime("%Y-%m-%d")
            else:
                edate = str(idx)[:10]

            # Get price on that date
            price = yahoo_price(ticker, edate)
            try:
                surprise = float(row.get("Surprise(%)", 0) or 0)
            except (ValueError, TypeError):
                surprise = 0

            earnings_list.append(
                {
                    "date": edate,
                    "eps_estimate": row.get("EPS Estimate"),
                    "eps_actual": row.get("Reported EPS"),
                    "surprise_pct": round(surprise, 2),
                    "price_open": price.get("open"),
                    "price_close": price.get("close"),
                    "price_change_pct": price.get("change_pct"),
                }
            )

    # 2. Get insider Filings (Form 4)
    padded = cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        sec_data = json.loads(resp.read())

    filings = sec_data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])

    # Count Form 4 filings per quarter
    insider_by_quarter = {}
    for i in range(len(forms)):
        if forms[i] != "4":
            continue
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
        # Map to quarter
        q = f"{fd.year}-Q{(fd.month - 1) // 3 + 1}"
        insider_by_quarter[q] = insider_by_quarter.get(q, 0) + 1

    # 3. Get 10-Q/10-K filing dates (quarterly reports)
    quarterly_reports = []
    for i in range(len(forms)):
        if forms[i] in ("10-Q", "10-K"):
            try:
                fd = datetime.strptime(dates[i], "%Y-%m-%d")
            except (ValueError, IndexError):
                continue
            acc = accs[i] if i < len(accs) else ""
            quarterly_reports.append(
                {
                    "form": forms[i],
                    "filing_date": dates[i],
                    "accession_number": acc,
                }
            )
            if len(quarterly_reports) >= quarters:
                break

    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "earnings": earnings_list,
        "insider_filings_by_quarter": insider_by_quarter,
        "quarterly_reports": quarterly_reports,
    }


@app.get("/filing")
def filing_detail(
    acc: str = Query(..., description="Accession number (with dashes)"),
    cik: str = Query(..., description="Company CIK"),
):
    """Fetch and attempt to parse Form 4 XML from SEC Archives."""
    acc_clean = acc.replace("-", "")
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{acc_clean}/{acc}.txt"
    )
    req = urllib.request.Request(
        url, headers={**HEADERS, "Accept": "text/html,application/xml"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    return {
        "accession_number": acc,
        "cik": cik,
        "url": url,
        "size": len(raw),
        "preview": raw[:2000],
    }


@app.get("/institutional/ticker")
def institutional_by_ticker(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    lookback: int = Query(180, description="Lookback days for 13F filings"),
):
    """List recent 13F institutional filings for a company."""
    cik = cik_from_ticker(ticker)
    padded = cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])
    rdates = filings.get("reportDate", [])

    cutoff = datetime.now() - timedelta(days=lookback)
    result = []
    for i in range(len(forms)):
        if forms[i] not in ("13F-HR", "13F-HR/A"):
            continue
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
        if fd < cutoff:
            continue
        acc = accs[i] if i < len(accs) else ""
        doc = docs[i] if i < len(docs) else ""
        result.append({
            "form": forms[i],
            "filing_date": dates[i],
            "report_date": rdates[i] if i < len(rdates) else "",
            "accession_number": acc,
            "primary_document": doc,
        })

    return {"ticker": ticker.upper(), "cik": cik, "filings": result, "count": len(result)}


@app.get("/institutional/holdings")
def institutional_holdings(
    cik: str = Query(..., description="Institution CIK (e.g. 1067983 for Berkshire)"),
    acc: str = Query(..., description="13F accession number with dashes"),
):
    """Parse a 13F filing XML and return holdings."""
    import xml.etree.ElementTree as ET

    acc_clean = acc.replace("-", "")
    # 13F filings: the information table is in a separate XML file
    # Usually named like 'primary_doc.xml' or 'xslForm13F_X02/form13fInfoTable.xml'
    # Try the main document first, then fall back to the info table
    urls_to_try = [
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{acc_clean}.txt",
    ]

    xml_content = None
    for u in urls_to_try:
        req = urllib.request.Request(u, headers={**HEADERS, "Accept": "text/html,application/xml"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        # Look for the XML info table section
        # 13F filings embed the info table XML between <XML> tags in the .txt
        xml_start = raw.find("<informationTable")
        if xml_start == -1:
            xml_start = raw.find("<ns1:informationTable")
        xml_end = raw.find("</informationTable>")
        if xml_end == -1:
            xml_end = raw.find("</ns1:informationTable>")

        if xml_start != -1 and xml_end != -1:
            xml_content = raw[xml_start : xml_end + len("</informationTable>")]
            break

    if not xml_content:
        raise HTTPException(404, detail="No 13F information table found in filing")

    # Parse holdings
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise HTTPException(500, detail=f"XML parse error: {str(e)[:200]}")

    holdings = []
    for entry in root.iter():
        tag = entry.tag.split("}")[-1] if "}" in entry.tag else entry.tag
        if tag not in ("infoTable", "entry"):
            continue

        item = {}
        for child in entry:
            ct = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            item[ct] = (child.text or "").strip()

        if item.get("nameOfIssuer"):
            holdings.append({
                "issuer": item.get("nameOfIssuer", ""),
                "class": item.get("titleOfClass", ""),
                "cusip": item.get("cusip", ""),
                "value_x1000": item.get("value", ""),
                "shares": item.get("sshPrnamt", ""),
                "put_call": item.get("putCall", ""),
                "discretion": item.get("investmentDiscretion", ""),
                "sole_voting": item.get("votingAuthority", {}).get("Sole", "") if isinstance(item.get("votingAuthority"), dict) else "",
            })

    return {
        "cik": cik,
        "accession_number": acc,
        "holdings": holdings,
        "count": len(holdings),
    }


@app.get("/institutional/nasdaq")
def nasdaq_holders(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
):
    """Get institutional ownership from NASDAQ API."""
    url = f"https://api.nasdaq.com/api/company/{ticker.upper()}/institutional-holdings?limit=20&type=TOTAL&sortBy=marketValue"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        raise HTTPException(502, detail=f"NASDAQ API failed: {e}")

    summary = data.get("data", {}).get("ownershipSummary", {})
    active = data.get("data", {}).get("activePositions", {})
    holders_list = active.get("rows", [])

    holders = []
    for row in holders_list[:20]:
        holders.append({
            "holder": row.get("ownerName", ""),
            "shares": row.get("sharesHeld", ""),
            "value": row.get("marketValue", ""),
            "change": row.get("sharesChange", ""),
            "change_pct": row.get("sharesChangePct", ""),
        })

    return {
        "ticker": ticker.upper(),
        "institutional_ownership": summary.get("SharesOutstandingPCT", {}).get("value", "N/A"),
        "total_value": summary.get("TotalHoldingsValue", {}).get("value", "N/A"),
        "holders": holders,
        "holders_count": len(holders),
    }


@app.get("/institutional/search")
def institutional_search(
    ticker: str = Query(..., description="Stock ticker to search in 13F filings"),
    limit: int = Query(20, description="Max results"),
):
    """
    Reverse 13F search: find institutions that filed 13F mentioning this stock.
    Uses SEC EDGAR full-text search.
    """
    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q={ticker.upper()}"
        f"&forms=13F-HR"
        f"&from=0"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    hits = data.get("hits", {}).get("hits", [])
    total = data.get("hits", {}).get("total", {}).get("value", 0)

    results = []
    for hit in hits[:limit]:
        src = hit.get("_source", {})
        results.append({
            "filer": src.get("display_names", [""])[0],
            "cik": src.get("ciks", [""])[0],
            "filing_date": src.get("file_date", ""),
            "form": src.get("form", ""),
            "adsh": src.get("adsh", ""),
        })

    return {
        "ticker": ticker.upper(),
        "total_13f_filings": total,
        "institutions": results,
        "count": len(results),
    }


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
