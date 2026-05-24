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

HEADERS = {
    "User-Agent": "MyCompany james0015@proton.me",
    "Accept": "application/json",
}


def fetch_insider_trades(cik: str, lookback_days: int = 90) -> list:
    """Fetch Form 4 insider trades from SEC EDGAR API using efts.sec.gov."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    all_results = []
    from_idx = 0

    while True:
        url = (
            f"https://efts.sec.gov/LATEST/search-index"
            f"?q={cik}"
            f"&dateRange=custom"
            f"&category=form-cat2"
            f"&startdt={start_str}"
            f"&enddt={end_str}"
            f"&forms=4"
            f"&from={from_idx}"
        )
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            raise HTTPException(
                status_code=502,
                detail=f"SEC API HTTP {e.code}: {body}",
            )
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=502,
                detail=f"SEC returned non-JSON: {raw[:500]}",
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
        shares = src.get("sharesTraded", 0) or 0
        price = src.get("pricePerShare", 0) or 0
        trades.append(
            {
                "filing_date": src.get("fileDate", ""),
                "company": src.get("companyName", ""),
                "ticker": src.get("issuerTradingSymbol", ""),
                "insider_name": src.get("reportingOwnerName", ""),
                "title": src.get("reportingOwnerTitle", ""),
                "transaction_type": src.get("transactionCode", ""),
                "shares": shares,
                "price": price,
                "total_value": shares * abs(price),
                "shares_owned_after": src.get("sharesOwnedAfterTransaction", 0),
                "form_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{src.get('accessionNo', '').replace('-', '')}/"
                    f"{src.get('primaryDocument', '')}"
                ),
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
    # First, get CIK from ticker via SEC company_tickers.json
    cik_url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(cik_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            company_data = json.loads(resp.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load ticker list: {e}")

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


@app.get("/debug/efts")
def debug_efts(
    cik: str = Query("320193", description="CIK number"),
    lookback: int = Query(90, description="Lookback days"),
):
    """Debug: return raw SEC efts response."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback)

    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q={cik}"
        f"&dateRange=custom"
        f"&category=form-cat2"
        f"&startdt={start_date.strftime('%Y-%m-%d')}"
        f"&enddt={end_date.strftime('%Y-%m-%d')}"
        f"&forms=4"
        f"&from=0"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return {
                "url": url,
                "status": resp.status,
                "total_hits": json.loads(raw).get("hits", {}).get("total", {}),
                "hit_count": len(json.loads(raw).get("hits", {}).get("hits", [])),
                "raw_length": len(raw),
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
