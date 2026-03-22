import requests
import finnhub
import yfinance as yf
from app.utils import SEC_HEADERS
from config import FINNHUB_API_KEY, COMMODITY_TICKERS, COMMODITY_KEYWORDS, ETF_TICKERS

_client = finnhub.Client(api_key=FINNHUB_API_KEY)


def get_price(ticker: str) -> dict:
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS:
        return _yf_price(COMMODITY_TICKERS.get(t, t), "commodity")
    if t in ETF_TICKERS:
        return _yf_price(ticker, "etf")
    return _stock_price(ticker)


def _yf_price(symbol: str, asset_type: str) -> dict:
    """Shared yfinance price fetch used for both commodities and ETFs."""
    try:
        t    = yf.Ticker(symbol)
        hist = t.history(period="2d")
        if hist.empty:
            return {"error": "No data"}
        cur  = round(float(hist["Close"].iloc[-1]), 2)
        prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else cur
        result = {
            "current_price": cur,
            "change_pct":    round((cur - prev) / prev * 100, 2),
            "high_today":    round(float(hist["High"].iloc[-1]), 2),
            "low_today":     round(float(hist["Low"].iloc[-1]),  2),
            "asset_type":    asset_type,
        }
        if asset_type == "etf":
            result["industry"] = t.info.get("category", "ETF")
        return result
    except Exception as e:
        return {"error": str(e)}


def _stock_price(ticker: str) -> dict:
    try:
        q = _client.quote(ticker)
        p = _client.company_profile2(symbol=ticker)
        return {
            "current_price": q.get("c", 0),
            "change_pct":    round(q.get("dp", 0), 2),
            "high_today":    q.get("h", 0),
            "low_today":     q.get("l", 0),
            "industry":      p.get("finnhubIndustry", "N/A"),
            "market_cap":    p.get("marketCapitalization", 0),
            "asset_type":    "stock",
        }
    except Exception as e:
        return {"error": str(e)}


def get_sec_data(ticker: str) -> dict:
    """Fetch latest 10-K and 10-Q filing dates from SEC EDGAR."""
    if ticker.upper() in COMMODITY_KEYWORDS or ticker.upper() in ETF_TICKERS:
        return {"skipped": "No SEC filings for commodities/ETFs"}
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS, timeout=10,
        ).json()
        cik = next(
            (str(e["cik_str"]).zfill(10) for e in resp.values()
             if e["ticker"].upper() == ticker.upper()),
            None,
        )
        if not cik:
            return {"error": "Ticker not found in SEC"}
        data   = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS, timeout=10,
        ).json()
        recent = data.get("filings", {}).get("recent", {})
        forms  = recent.get("form", [])
        dates  = recent.get("filingDate", [])
        latest_10k = latest_10q = None
        for form, date in zip(forms, dates):
            if form == "10-K" and not latest_10k:
                latest_10k = {"form": form, "date": date}
            if form == "10-Q" and not latest_10q:
                latest_10q = {"form": form, "date": date}
            if latest_10k and latest_10q:
                break
        return {"cik": cik, "latest_10k": latest_10k, "latest_10q": latest_10q}
    except Exception as e:
        return {"error": str(e)}
