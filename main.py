"""SEC EDGAR Insider Trading Proxy API
Deployed on US-based server (Hetzner Virginia) to bypass SEC geo-restrictions.
Called by n8n Code node for insider trading data.
"""

import json
import urllib.request
from datetime import datetime, timedelta

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="SEC EDGAR Proxy", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SEC_EDGAR_URL = "https://efts.sec.gov/LATEST/search-index?q={ciq}&dateRange=custom&category=form-cat2&startdt={start}&enddt={end}&forms=4&from={from_idx}"

HEADERS = {
    "User-Agent": "MyCompany james0015@proton.me",
    "Accept": "application/json",
}


def fetch_insider_trades(cik: str, lookback_days: int = 90) -> list:
    """Fetch Form 4 insider trades from SEC EDGAR API."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    all_results = []
    from_idx = 0

    while True:
        url = SEC_EDGAR_URL.format(
            ciq=cik,
            start=start_str,
            end=end_str,
            from_idx=from_idx,
        )
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise HTTPException(
                status_code=502,
                detail=f"SEC API error: {e.code} - {e.read().decode()[:200]}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        hits = data.get("hits", {}).get("hits", [])
        all_results.extend(hits)

        total = data.get("hits", {}).get("total", {}).get("value", 0)
        from_idx += len(hits)
        if from_idx >= total or len(hits) == 0:
            break

    # Normalize
    trades = []
    for hit in all_results:
        src = hit.get("_source", {})
        trades.append(
            {
                "filing_date": src.get("fileDate", ""),
                "company": src.get("companyName", ""),
                "ticker": src.get("issuerTradingSymbol", ""),
                "insider_name": src.get("reportingOwnerName", ""),
                "title": src.get("reportingOwnerTitle", ""),
                "transaction_type": src.get("transactionCode", ""),
                "shares": src.get("sharesTraded", 0),
                "price": src.get("pricePerShare", 0),
                "total_value": src.get("sharesTraded", 0) * src.get("pricePerShare", 0),
                "shares_owned_after": src.get("sharesOwnedAfterTransaction", 0),
                "form_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{src.get('accessionNo','').replace('-','')}/{src.get('primaryDocument','')}",
            }
        )

    return trades


@app.get("/")
def root():
    return {"service": "SEC EDGAR Proxy", "status": "running"}


@app.get("/insider")
def insider_trades(
    cik: str = Query(..., description="CIK number (e.g. 320193 for AAPL/Apple)"),
    lookback: int = Query(90, description="Lookback days (default 90)"),
):
    """Get insider trading data for a company by CIK."""
    trades = fetch_insider_trades(cik, lookback)
    return {
        "cik": cik,
        "trades": trades,
        "count": len(trades),
        "lookback_days": lookback,
    }


@app.get("/insider/ticker")
def insider_by_ticker(
    ticker: str = Query(..., description="Stock ticker (e.g. AAPL)"),
    lookback: int = Query(90, description="Lookback days (default 90)"),
):
    """Get insider trading data by ticker symbol (auto-resolves CIK)."""
    # First, get CIK from ticker
    cik_url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(cik_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            company_data = json.loads(resp.read())
    except Exception:
        # Fallback: direct lookup
        cik_url = f"https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&category=form-cat2&startdt=2024-01-01&enddt=2024-01-02&forms=4&from=0"
        req = urllib.request.Request(cik_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                raise HTTPException(status_code=404, detail=f"No SEC data for ticker: {ticker}")
            cik = hits[0].get("_source", {}).get("cik", "")
            if not cik:
                raise HTTPException(status_code=404, detail=f"CIK not found for ticker: {ticker}")
    else:
        # Find CIK from company_tickers.json
        cik = None
        ticker_upper = ticker.upper()
        for _, info in company_data.items():
            if info.get("ticker", "").upper() == ticker_upper:
                cik = str(info["cik_str"])
                break
        if not cik:
            raise HTTPException(status_code=404, detail=f"Ticker not found: {ticker}")

    trades = fetch_insider_trades(cik, lookback)
    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "trades": trades,
        "count": len(trades),
        "lookback_days": lookback,
    }


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
