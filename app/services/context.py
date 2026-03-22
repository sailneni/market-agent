import re, requests, finnhub
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from app.utils import SEC_HEADERS
from config import FINNHUB_API_KEY

_client = finnhub.Client(api_key=FINNHUB_API_KEY)

_FG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Accept": "application/json",
}

# Fear & Greed thresholds: score >= threshold → label
_FG_SIGNALS = [
    (75, "EXTREME GREED 🔴 — market likely overbought"),
    (55, "GREED 🟠 — be cautious"),
    (45, "NEUTRAL 🟡"),
    (25, "FEAR 🔵 — potential buying opportunity"),
    (0,  "EXTREME FEAR 🟢 — strong contrarian buy signal"),
]


def _fg_signal(score: float) -> str:
    return next(sig for thresh, sig in _FG_SIGNALS if score >= thresh)


def get_fear_and_greed() -> dict:
    for url in [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/",
    ]:
        try:
            resp = requests.get(url, headers=_FG_HEADERS, timeout=10)
            if resp.status_code == 200:
                fg    = resp.json().get("fear_and_greed", {})
                score = round(float(fg.get("score", 0)), 1)
                return {
                    "score":  score,
                    "rating": fg.get("rating", "N/A"),
                    "signal": _fg_signal(score),
                    "previous_close":   round(float(fg.get("previous_close",   0)), 1),
                    "previous_1_week":  round(float(fg.get("previous_1_week",  0)), 1),
                    "previous_1_month": round(float(fg.get("previous_1_month", 0)), 1),
                    "source": "CNN",
                }
        except Exception:
            continue
    # Fallback
    try:
        resp  = requests.get("https://feargreedmeter.com",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        match = re.search(r'(\d+)\s*\(?(Extreme Fear|Fear|Neutral|Greed|Extreme Greed)\)?', resp.text)
        if match:
            score = int(match.group(1))
            return {"score": score, "rating": match.group(2),
                    "signal": _fg_signal(score), "source": "feargreedmeter.com"}
    except Exception:
        pass
    return {"error": "Fear & Greed unavailable"}


def get_earnings_calendar(tickers: list) -> dict:
    try:
        today  = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        cal    = _client.earnings_calendar(_from=today, to=future, symbol="", international=False)

        # Index by symbol once instead of doing N linear scans
        by_symbol = {}
        for e in cal.get("earningsCalendar", []):
            sym = e.get("symbol", "").upper()
            if sym not in by_symbol:
                by_symbol[sym] = e

        result = {}
        for ticker in tickers:
            e = by_symbol.get(ticker.upper())
            if not e:
                result[ticker] = {"status": "No upcoming earnings in 90 days"}
                continue
            try:
                days    = (datetime.strptime(e["date"], "%Y-%m-%d") - datetime.now()).days
                urgency = "🔥 THIS WEEK" if days <= 7 else "⚡ THIS MONTH" if days <= 30 else "📅 UPCOMING"
            except Exception:
                days, urgency = None, "📅 UPCOMING"
            result[ticker] = {
                "date":         e.get("date"),
                "quarter":      f"Q{e.get('quarter')} {e.get('year')}",
                "eps_estimate": e.get("epsEstimate"),
                "days_until":   days,
                "urgency":      urgency,
            }
        return result
    except Exception as e:
        return {"error": str(e)}


def get_insider_trading(ticker: str) -> dict:
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
            return {"error": f"CIK not found for {ticker}"}
        data   = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS, timeout=10,
        ).json()
        recent = data.get("filings", {}).get("recent", {})
        form4s = [
            {"date": d}
            for f, d in zip(recent.get("form", []), recent.get("filingDate", []))
            if f == "4"
        ][:10]
        c30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        c90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        f30 = sum(1 for f in form4s if f["date"] >= c30)
        f90 = sum(1 for f in form4s if f["date"] >= c90)
        signal = ("🔥 HIGH insider activity (30d)" if f30 >= 3
                  else "📈 Some insider activity (30d)" if f30 >= 1
                  else "🟡 Moderate insider activity (90d)" if f90 >= 3
                  else "😴 Low insider activity")
        return {"ticker": ticker, "recent_filings_30d": f30,
                "recent_filings_90d": f90, "signal": signal}
    except Exception as e:
        return {"error": str(e)}


def get_market_context(tickers: list) -> dict:
    """Fetch all market context in parallel."""
    context = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        fg_f       = pool.submit(get_fear_and_greed)
        earnings_f = pool.submit(get_earnings_calendar, tickers)
        insider_fs = {t: pool.submit(get_insider_trading, t) for t in tickers}
        context["fear_and_greed"]    = fg_f.result()
        context["earnings_calendar"] = earnings_f.result()
        context["insider_trading"]   = {t: f.result() for t, f in insider_fs.items()}
    return context
