#!/usr/bin/env python3
"""
SEC Filing → NotebookLM Audio Overview Pipeline

Usage:
    python nb_finance.py AAPL          # Latest 10-K → Chinese podcast
    python nb_finance.py TSLA --form 10-Q --quarters 2  # Last 2 10-Qs
    python nb_finance.py NVDA --language en  # English output

Prerequisites:
    pip install "notebooklm-py[browser]"
    notebooklm login
"""

import sys
import json
import urllib.request
import argparse
from datetime import datetime

PROXY = "https://sec-edgar.zeabur.app"
HEADERS = {"User-Agent": "NotebookLM-Finance/1.0"}


def get_cik(ticker: str) -> str:
    """Resolve ticker to CIK."""
    url = f"{PROXY}/insider/ticker?ticker={ticker}&lookback=1"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read())
        return data.get("cik", "")


def get_latest_10k_text(ticker: str) -> tuple[str, str, str]:
    """
    Fetch latest 10-K/10-Q text from SEC.
    Returns: (cik, filing_date, full_text)
    """
    # Use SEC submissions API directly for filing list
    cik = get_cik(ticker)
    padded = cik.zfill(10)

    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])

    # Find latest 10-K
    for i in range(len(forms)):
        if forms[i] in ("10-K", "10-K/A"):
            acc = accs[i]
            date = dates[i]
            doc = docs[i]

            # Fetch the filing text
            acc_clean = acc.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{acc_clean}/{acc_clean}.txt"
            )
            req2 = urllib.request.Request(filing_url, headers=HEADERS)
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                raw = resp2.read().decode("utf-8", errors="replace")

            return cik, date, raw[:500000]  # Limit to 500KB

    # Fallback: try 10-Q
    for i in range(len(forms)):
        if forms[i] in ("10-Q", "10-Q/A"):
            acc = accs[i]
            date = dates[i]
            acc_clean = acc.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{acc_clean}/{acc_clean}.txt"
            )
            req2 = urllib.request.Request(filing_url, headers=HEADERS)
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                raw = resp2.read().decode("utf-8", errors="replace")

            return cik, date, raw[:500000]

    raise RuntimeError(f"No 10-K or 10-Q found for {ticker}")


def extract_essentials(text: str) -> str:
    """
    Extract key financial sections from SEC filing.
    Targets: Business, Risk Factors, MD&A, Financial Statements.
    """
    sections = []

    # Try to find key sections
    markers = [
        ("ITEM 1.", "ITEM 1A."),    # Business
        ("ITEM 1A.", "ITEM 1B."),   # Risk Factors
        ("ITEM 7.", "ITEM 7A."),    # MD&A
        ("ITEM 8.", "ITEM 9."),     # Financial Statements
    ]

    for start_marker, end_marker in markers:
        start = text.find(start_marker)
        if start == -1:
            continue
        end = text.find(end_marker, start + len(start_marker))
        if end == -1:
            end = start + 50000  # Grab up to 50KB

        section = text[start:end]
        # Clean HTML/XML tags
        import re
        # Remove HTML tags
        section = re.sub(r"<[^>]+>", " ", section)
        # Remove XML
        section = re.sub(r"<[^>]+>", " ", section)
        # Collapse whitespace
        section = re.sub(r"\s+", " ", section)
        # Remove XBRL/encoded content
        section = re.sub(r"&#\d+;", "", section)

        sections.append(f"=== {start_marker} ===\n{section[:10000]}\n")

    if not sections:
        # Just take the text portion (after removing XML/HTML)
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"&#\d+;", "", clean)
        clean = re.sub(r"\s+", " ", clean)
        sections.append(clean[:50000])

    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(
        description="SEC Filing → NotebookLM Podcast"
    )
    parser.add_argument("ticker", help="Stock ticker (e.g. AAPL, TSLA)")
    parser.add_argument(
        "--language", default="zh-TW",
        help="Audio language (default: zh-TW, also: en, ja, zh-CN)"
    )
    parser.add_argument(
        "--format", default="deep-dive",
        choices=["deep-dive", "brief", "critique", "debate"],
        help="Audio overview format (default: deep-dive)"
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Only extract filing text, don't generate audio"
    )

    args = parser.parse_args()
    ticker = args.ticker.upper()

    print(f"📊 Fetching {ticker} latest 10-K/10-Q...")
    cik, date, raw_text = get_latest_10k_text(ticker)
    print(f"   CIK: {cik}, Filed: {date}, Size: {len(raw_text):,} chars")

    print("🔍 Extracting key sections...")
    clean_text = extract_essentials(raw_text)
    print(f"   Cleaned: {len(clean_text):,} chars")

    if args.extract_only:
        output_file = f"{ticker}_{date}_10K.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(clean_text)
        print(f"✅ Saved to {output_file}")
        return

    print(f"🎙️  Creating NotebookLM notebook + generating {args.format} audio ({args.language})...")
    print("   (This may take 5-10 minutes)")

    # --- NotebookLM automation ---
    from notebooklm import NotebookLM

    nlm = NotebookLM()

    # Create notebook
    notebook_name = f"{ticker} {date} 10-K Analysis"
    notebook = nlm.notebooks.create(notebook_name)
    print(f"   Notebook: {notebook.name} ({notebook.id})")

    # Add source (paste text directly)
    source = nlm.sources.add_text(
        notebook.id,
        clean_text,
        title=f"{ticker} 10-K filed {date}"
    )
    print(f"   Source added: {source.id}")

    # Wait for processing
    print("   Waiting for source processing...")
    nlm.sources.wait_until_ready(source.id)
    print("   ✅ Source ready")

    # Generate audio overview
    print(f"   Generating {args.format} audio overview...")
    audio = nlm.artifacts.generate_audio(
        notebook.id,
        format=args.format,
        language=args.language,
    )
    print(f"   Audio artifact: {audio.id}")

    # Wait for generation
    print("   Waiting for audio generation (this takes several minutes)...")
    nlm.artifacts.wait_until_ready(audio.id)
    print("   ✅ Audio ready")

    # Download
    filename = f"{ticker}_{date}_podcast_{args.language}.mp3"
    print(f"   Downloading to {filename}...")
    nlm.artifacts.download(audio.id, filename)

    print(f"\n✅ Done! Podcast saved to: {filename}")
    print(f"   Notebook: https://notebooklm.google.com/notebook/{notebook.id}")


if __name__ == "__main__":
    main()
