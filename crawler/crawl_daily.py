#!/usr/bin/env python3
"""
SEC 每日籌碼爬蟲 — 運行於 Hermes，透過美國 proxy 爬取

爬取內容：
    1. 內部人交易 (Form 4) — 關注清單每檔
    2. 機構持股 (13F) — 主要機構投資人
    3. 存到 GitHub + 本機 JSON

Usage:
    python3 crawl_daily.py              # 手動執行一次
    python3 crawl_daily.py --tickers AAPL,TSLA,NVDA,MSFT,META  # 自訂清單
"""

import json
import urllib.request
import sys
import os
from datetime import datetime, timedelta

PROXY = "https://sec-edgar.zeabur.app"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SEC-Crawler/1.0)"}

# 預設關注清單
WATCHLIST = [
    {"ticker": "AAPL", "cik": "320193"},
    {"ticker": "TSLA", "cik": "1318605"},
    {"ticker": "NVDA", "cik": "1045810"},
    {"ticker": "MSFT", "cik": "789019"},
    {"ticker": "META", "cik": "1326801"},
    {"ticker": "GOOGL", "cik": "1652044"},
    {"ticker": "AMZN", "cik": "1018724"},
    {"ticker": "BRK-B", "cik": "1067983"},
    {"ticker": "JPM", "cik": "19617"},
    {"ticker": "V", "cik": "1403161"},
]

# 主要機構投資人（追蹤他們的 13F 申報）
INSTITUTIONS = [
    {"name": "Berkshire Hathaway", "ticker": "BRK-B", "cik": "1067983"},
    {"name": "BlackRock", "ticker": "BLK", "cik": "1364742"},
    {"name": "Vanguard", "ticker": "VOO", "cik": "102909"},
    {"name": "State Street", "ticker": "STT", "cik": "93751"},
    {"name": "Renaissance Technologies", "cik": "1037389"},
    {"name": "Baupost Group", "cik": "1061768"},
    {"name": "Pershing Square", "cik": "1336528"},
    {"name": "Tiger Global", "cik": "1167483"},
]


def fetch_json(url, timeout=20):
    """Fetch JSON from proxy."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def crawl_insider(ticker):
    """Crawl insider trades for a ticker."""
    try:
        data = fetch_json(f"{PROXY}/insider/ticker?ticker={ticker}&lookback=7")
        return {
            "ticker": ticker,
            "count": data.get("count", 0),
            "filings": data.get("filings", []),
        }
    except Exception as e:
        return {"ticker": ticker, "count": 0, "error": str(e)[:100]}


def crawl_institutional(inst):
    """Crawl 13F filings for an institution."""
    cik = inst.get("cik", "")
    name = inst.get("name", "")
    ticker = inst.get("ticker", "")
    
    try:
        if ticker:
            data = fetch_json(f"{PROXY}/institutional/ticker?ticker={ticker}")
        else:
            data = fetch_json(f"{PROXY}/insider/cik?cik={cik}&lookback=180")
            # Filter to 13F forms manually
            data = {"filings": [f for f in data.get("filings", []) if "13F" in f.get("form_type", "")]}
            data["count"] = len(data["filings"])
        filings = data.get("filings", [])
        # Get latest 13F holdings if available
        holdings = None
        if filings:
            latest = filings[0]
            try:
                hdata = fetch_json(
                    f"{PROXY}/institutional/holdings?cik={cik}&acc={latest['accession_number']}",
                    timeout=30,
                )
                holdings = hdata.get("holdings", [])[:50]  # Top 50 holdings
            except Exception:
                pass

        return {
            "name": name,
            "cik": cik,
            "filings_count": len(filings),
            "latest_filing": filings[0]["filing_date"] if filings else None,
            "top_holdings": holdings,
        }
    except Exception as e:
        return {"name": name, "cik": cik, "error": str(e)[:100]}


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"🕷️  SEC 每日籌碼爬蟲 — {today}")
    
    # Parse custom tickers
    custom_tickers = None
    for arg in sys.argv:
        if arg.startswith("--tickers="):
            custom_tickers = arg.split("=", 1)[1].split(",")
    
    watchlist = WATCHLIST
    if custom_tickers:
        watchlist = [{"ticker": t.strip().upper(), "cik": ""} for t in custom_tickers]

    # ── 1. 內部人交易 ──
    print(f"\n📊 內部人交易 ({len(watchlist)} 檔)")
    insider_results = []
    for stock in watchlist:
        result = crawl_insider(stock["ticker"])
        icon = "🔴" if result["count"] > 0 else "⚪"
        print(f"   {icon} {result['ticker']}: {result['count']} 筆")
        insider_results.append(result)

    # ── 2. 機構 13F ──
    print(f"\n📈 機構持股 ({len(INSTITUTIONS)} 家)")
    inst_results = []
    for inst in INSTITUTIONS[:5]:  # Limit to 5 to avoid rate limits
        result = crawl_institutional(inst)
        holdings_count = len(result.get("top_holdings") or [])
        fc = result.get("filings_count", result.get("count", 0))
        print(f"   📁 {result.get('name', '?')}: {fc} filings, {holdings_count} holdings")
        inst_results.append(result)

    # ── 3. 儲存結果 ──
    output = {
        "date": today,
        "generated_at": datetime.now().isoformat(),
        "insider": insider_results,
        "institutional": inst_results,
    }

    # Save local
    os.makedirs("/tmp/sec-crawl", exist_ok=True)
    fname = f"/tmp/sec-crawl/{today}.json"
    with open(fname, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Summary
    total_insider = sum(r["count"] for r in insider_results if "count" in r)
    print(f"\n✅ 完成！")
    print(f"   內部人交易：{total_insider} 筆")
    print(f"   機構報告：{len(inst_results)} 家")
    print(f"   儲存：{fname}")

    return output


if __name__ == "__main__":
    main()
