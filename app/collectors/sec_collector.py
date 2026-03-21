import requests

EDGAR_BASE = "https://data.sec.gov/submissions"
HEADERS = {"User-Agent": "Saiteja aillneni.teja@gmail.com"}

def get_company_filings(ticker: str) -> dict:
    """Get latest filings for a ticker from EDGAR."""
    # First resolve ticker to CIK
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(tickers_url, headers=HEADERS).json()
    cik = None
    for entry in resp.values():
        if entry["ticker"].upper() == ticker.upper():
            cik = str(entry["cik_str"]).zfill(10)
            break
    if not cik:
        return {"error": "Ticker not found"}

    filings_url = f"{EDGAR_BASE}/CIK{cik}.json"
    data = requests.get(filings_url, headers=HEADERS).json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    # Return last 5 10-Q or 10-K filings
    results = []
    for form, date in zip(forms, dates):
        if form in ("10-K", "10-Q"):
            results.append({"form": form, "date": date})
        if len(results) >= 5:
            break
    return {"ticker": ticker, "cik": cik, "filings": results}
