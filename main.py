"""SEC EDGAR Insider Trading Proxy API
Deployed on US-based server (Hetzner Virginia) to bypass SEC geo-restrictions.
Called by n8n Code node for insider trading data.

Field mapping (efts.sec.gov → our output):
  file_date → filing_date
  display_names[0] → company
  ciks[0] → cik
  form → form_type
  file_num → file_number
"""

import json
import urllib.request
from datetime import datetime, timedelta

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="SEC EDGAR Proxy", version="1.1.0")

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
    """
    Fetch Form 4 insider trades from SEC EDGAR.
    Note: dateRange=custom + startdt/enddt breaks the SEC API — we fetch
    recent filings without date filter and filter client-side.
    """
    cutoff_date = datetime.now() - timedelta(days=lookback_days)

    all_results = []
    from_idx = 0
    max_pages = 5  # safety limit

    while from_idx < max_pages * 100:
        url = (
            f"https://efts.sec.gov/LATEST/search-index"
            f"?q={cik}"
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
            raise HTTPException(status_code=502, detail=f"SEC API HTTP {e.code}: {body}")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=502, detail=f"SEC non-JSON: {raw[:500]}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        all_results.extend(hits)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        from_idx += len(hits)
        if from_idx >= total:
            break

    # Normalize with correct field names
    trades = []
    for hit in all_results:
        src = hit.get("_source", {})

        # Parse file_date
        file_date_str = src.get("file_date", "")
        try:
            file_date = datetime.strptime(file_date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            file_date = None

        # Client-side date filter
        if file_date and file_date < cutoff_date:
            continue

        # Extract fields
        ciks = src.get("ciks", [])
        display_names = src.get("display_names", [])
        adsh = src.get("adsh", "")
        form_type = src.get("form", "")

        company = display_names[0] if display_names else ""
        filing_cik = ciks[0] if ciks else cik

        trades.append(
            {
                "filing_date": file_date_str[:10] if file_date_str else "",
                "company": company,
                "cik": filing_cik,
                "form_type": form_type,
                "adsh": adsh,
                "file_num": src.get("file_num", ""),
                "period_ending": src.get("period_ending", ""),
                "items": src.get("items", []),
                "form_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{filing_cik}/"
                    f"{adsh.replace('-', '')}/"
                    f"{adsh.replace('-', '')}-index.htm"
                ) if adsh else "",
            }
        )

    return trades


@app.get("/")
def root():
    return {"service": "SEC EDGAR Proxy", "status": "running", "version": "1.1.0"}


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


@app.get("/debug/raw")
def debug_raw(
    cik: str = Query("320193", description="CIK number"),
):
    """Debug: return raw SEC efts response (no date filter)."""
    url = f"https://efts.sec.gov/LATEST/search-index?q={cik}&forms=4&from=0"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
            total = data.get("hits", {}).get("total", {}).get("value", 0)
            hits = data.get("hits", {}).get("hits", [])
            return {
                "url": url,
                "total_hits": total,
                "returned": len(hits),
                "sample_source_keys": (
                    sorted(hits[0].get("_source", {}).keys()) if hits else []
                ),
                "sample": hits[0].get("_source", {}) if hits else None,
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
