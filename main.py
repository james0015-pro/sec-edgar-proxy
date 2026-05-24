"""SEC EDGAR + Yahoo Finance Proxy API
Deployed on US-based server (Hetzner Virginia).

Endpoints:
  GET /insider/ticker?ticker=AAPL&lookback=90       — insider Form 4 filings
  GET /insider/cik?cik=320193&lookback=90            — insider by CIK
  GET /earnings?ticker=AAPL&quarters=8               — earnings history
  GET /price?ticker=AAPL&date=2026-04-27             — price on a date
  GET /compare?ticker=AAPL&quarters=8                — full comparison:
      earnings dates + price changes + insider filings + 13F windows
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
        f"{acc_clean}/{acc_clean}.txt"
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


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
