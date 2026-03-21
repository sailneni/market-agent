import requests
import finnhub
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════════
# 1. FEAR & GREED INDEX
# ═══════════════════════════════════════════════════════════

def get_fear_and_greed():
    print("  😨 Fetching Fear & Greed Index...")

    # Try multiple known CNN endpoints
    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.cnn.com/markets/fear-and-greed",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.cnn.com"
    }

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.text.strip():
                data = resp.json()
                fg = data.get("fear_and_greed", {})
                score = round(float(fg.get("score", 0)), 1)
                rating = fg.get("rating", "N/A")
                prev_close = round(float(fg.get("previous_close", 0)), 1)
                prev_1w = round(float(fg.get("previous_1_week", 0)), 1)
                prev_1m = round(float(fg.get("previous_1_month", 0)), 1)

                if score >= 75:
                    signal = "EXTREME GREED 🔴 — market likely overbought"
                elif score >= 55:
                    signal = "GREED 🟠 — be cautious, consider taking profits"
                elif score >= 45:
                    signal = "NEUTRAL 🟡 — no strong directional bias"
                elif score >= 25:
                    signal = "FEAR 🔵 — potential buying opportunity"
                else:
                    signal = "EXTREME FEAR 🟢 — strong contrarian buy signal"

                return {
                    "score": score,
                    "rating": rating,
                    "signal": signal,
                    "previous_close": prev_close,
                    "previous_1_week": prev_1w,
                    "previous_1_month": prev_1m,
                    "interpretation": (
                        "Buffett Rule: Be greedy when others are fearful, "
                        "fearful when others are greedy."
                    ),
                    "source": "CNN"
                }
        except Exception:
            continue

    # ── Fallback: scrape feargreedmeter.com ───────────────
    try:
        resp = requests.get(
            "https://feargreedmeter.com",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        match = re.search(
            r'(\d+)\s*\(?(Extreme Fear|Fear|Neutral|Greed|Extreme Greed)\)?',
            resp.text
        )
        if match:
            score = int(match.group(1))
            rating = match.group(2)

            if score >= 75:
                signal = "EXTREME GREED 🔴 — market likely overbought"
            elif score >= 55:
                signal = "GREED 🟠 — be cautious, consider taking profits"
            elif score >= 45:
                signal = "NEUTRAL 🟡 — no strong directional bias"
            elif score >= 25:
                signal = "FEAR 🔵 — potential buying opportunity"
            else:
                signal = "EXTREME FEAR 🟢 — strong contrarian buy signal"

            return {
                "score": score,
                "rating": rating,
                "signal": signal,
                "previous_close": "N/A",
                "previous_1_week": "N/A",
                "previous_1_month": "N/A",
                "source": "feargreedmeter.com",
                "interpretation": (
                    "Buffett Rule: Be greedy when others are fearful, "
                    "fearish when others are greedy."
                )
            }
    except Exception as e:
        pass

    return {"error": "All Fear & Greed sources unavailable"}


# ═══════════════════════════════════════════════════════════
# 2. EARNINGS CALENDAR
# ═══════════════════════════════════════════════════════════

def get_earnings_calendar(tickers):
    print("  📅 Fetching earnings calendar...")
    try:
        client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

        calendar = client.earnings_calendar(
            _from=today,
            to=future,
            symbol="",
            international=False
        )

        earnings_list = calendar.get("earningsCalendar", [])
        result = {}

        for ticker in tickers:
            ticker_earnings = []
            for entry in earnings_list:
                if entry.get("symbol", "").upper() == ticker.upper():
                    date = entry.get("date", "N/A")
                    eps_est = entry.get("epsEstimate")
                    rev_est = entry.get("revenueEstimate")
                    quarter = entry.get("quarter", "N/A")
                    year = entry.get("year", "N/A")

                    # Days until earnings
                    try:
                        earn_date = datetime.strptime(date, "%Y-%m-%d")
                        days_until = (earn_date - datetime.now()).days
                        urgency = (
                            "🔥 THIS WEEK" if days_until <= 7
                            else "⚡ THIS MONTH" if days_until <= 30
                            else "📅 UPCOMING"
                        )
                    except Exception:
                        days_until = None
                        urgency = "📅 UPCOMING"

                    ticker_earnings.append({
                        "date": date,
                        "quarter": f"Q{quarter} {year}",
                        "eps_estimate": eps_est,
                        "revenue_estimate": rev_est,
                        "days_until": days_until,
                        "urgency": urgency
                    })

            if ticker_earnings:
                result[ticker] = sorted(
                    ticker_earnings,
                    key=lambda x: x["date"]
                )[0]  # Only keep next upcoming
            else:
                result[ticker] = {"status": "No upcoming earnings found in 90 days"}

        return result

    except Exception as e:
        print(f"  ⚠️  Earnings calendar fetch failed: {e}")
        return {"error": str(e)}


def get_earnings_history(ticker):
    print(f"  📊 Fetching earnings history for {ticker}...")
    try:
        client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))
        data = client.company_earnings(ticker, limit=4)

        history = []
        for entry in data:
            actual = entry.get("actual")
            estimate = entry.get("estimate")
            surprise_pct = None
            beat = None

            if actual is not None and estimate is not None and estimate != 0:
                surprise_pct = round(((actual - estimate) / abs(estimate)) * 100, 2)
                beat = actual >= estimate

            history.append({
                "period": entry.get("period", "N/A"),
                "actual_eps": actual,
                "estimated_eps": estimate,
                "surprise_pct": surprise_pct,
                "beat": beat,
                "result": "✅ BEAT" if beat else "❌ MISS" if beat is False else "N/A"
            })

        beats = sum(1 for h in history if h.get("beat") is True)
        beat_rate = f"{beats}/{len(history)}" if history else "N/A"

        return {
            "ticker": ticker,
            "last_4_quarters": history,
            "beat_rate": beat_rate,
            "consistent_beater": beats >= 3
        }

    except Exception as e:
        print(f"  ⚠️  Earnings history failed for {ticker}: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
# 3. INSIDER TRADING (SEC FORM 4)
# ═══════════════════════════════════════════════════════════

SEC_HEADERS = {"User-Agent": "MarketAgent marketagent@email.com"}


def get_insider_trading(ticker):
    print(f"  🏦 Fetching insider trading for {ticker}...")
    try:
        # Get CIK
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        resp = requests.get(tickers_url, headers=SEC_HEADERS).json()
        cik = None
        for entry in resp.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break

        if not cik:
            return {"error": f"CIK not found for {ticker}"}

        # Get Form 4 filings
        filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = requests.get(filings_url, headers=SEC_HEADERS).json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])

        form4_filings = []
        for form, date, acc in zip(forms, dates, accessions):
            if form == "4":
                form4_filings.append({"date": date, "accession": acc})
            if len(form4_filings) >= 10:
                break

        if not form4_filings:
            return {
                "ticker": ticker,
                "recent_filings": [],
                "signal": "⚪ No recent Form 4 filings found",
                "summary": "No insider activity detected"
            }

        # Analyze filing dates for activity clusters
        cutoff_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cutoff_90d = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        filings_30d = [f for f in form4_filings if f["date"] >= cutoff_30d]
        filings_90d = [f for f in form4_filings if f["date"] >= cutoff_90d]

        if len(filings_30d) >= 3:
            signal = "🔥 HIGH insider activity in last 30 days — watch closely"
        elif len(filings_30d) >= 1:
            signal = "📈 Some insider activity in last 30 days"
        elif len(filings_90d) >= 3:
            signal = "🟡 Moderate insider activity in last 90 days"
        else:
            signal = "😴 Low insider activity recently"

        return {
            "ticker": ticker,
            "recent_filings_30d": len(filings_30d),
            "recent_filings_90d": len(filings_90d),
            "latest_filing_date": form4_filings[0]["date"] if form4_filings else "N/A",
            "signal": signal,
            "filings": form4_filings[:5]
        }

    except Exception as e:
        print(f"  ⚠️  Insider trading fetch failed for {ticker}: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
# 4. COMBINED CONTEXT — call this from test_agent / watcher
# ═══════════════════════════════════════════════════════════

def get_market_context(tickers):
    print("\n🌍 Fetching market context...")
    context = {}

    # Fear & Greed — market wide
    context["fear_and_greed"] = get_fear_and_greed()

    # Per-ticker data
    context["earnings_calendar"] = get_earnings_calendar(tickers)
    context["insider_trading"] = {}
    context["earnings_history"] = {}

    for ticker in tickers:
        context["insider_trading"][ticker] = get_insider_trading(ticker)
        context["earnings_history"][ticker] = get_earnings_history(ticker)

    print("  ✅ Market context complete!")
    return context


# ═══════════════════════════════════════════════════════════
# PRINT HELPERS
# ═══════════════════════════════════════════════════════════

def print_market_context(context, tickers):
    print("\n" + "=" * 65)
    print("🌍  MARKET CONTEXT REPORT")
    print("=" * 65)

    fg = context.get("fear_and_greed", {})
    if "error" not in fg:
        print(f"\n😨 FEAR & GREED INDEX")
        print(f"   Score        : {fg.get('score')} / 100")
        print(f"   Rating       : {fg.get('rating', '').upper()}")
        print(f"   Signal       : {fg.get('signal')}")
        print(f"   Prev Close   : {fg.get('previous_close')}")
        print(f"   1 Week Ago   : {fg.get('previous_1_week')}")
        print(f"   1 Month Ago  : {fg.get('previous_1_month')}")
        print(f"   Source       : {fg.get('source', 'CNN')}")
        print(f"   💡 {fg.get('interpretation')}")

    for ticker in tickers:
        print(f"\n{'─' * 65}")
        print(f"  📌 {ticker}")

        # Earnings calendar
        ec = context.get("earnings_calendar", {}).get(ticker, {})
        if "error" not in ec and "status" not in ec:
            print(f"\n  📅 NEXT EARNINGS:")
            print(f"     Date        : {ec.get('date')} ({ec.get('urgency')})")
            print(f"     Quarter     : {ec.get('quarter')}")
            print(f"     EPS Est.    : {ec.get('eps_estimate', 'N/A')}")
            print(f"     Rev Est.    : {ec.get('revenue_estimate', 'N/A')}")
            if ec.get("days_until") is not None:
                print(f"     Days Until  : {ec.get('days_until')} days")
        else:
            print(f"\n  📅 EARNINGS: {ec.get('status', ec.get('error', 'N/A'))}")

        # Earnings history
        eh = context.get("earnings_history", {}).get(ticker, {})
        if "error" not in eh:
            print(f"\n  📊 EARNINGS HISTORY (last 4Q):")
            print(f"     Beat Rate   : {eh.get('beat_rate')} quarters")
            print(f"     Consistent  : {'✅ Yes' if eh.get('consistent_beater') else '❌ No'}")
            for q in eh.get("last_4_quarters", []):
                print(f"     {q.get('period')} : {q.get('result')} "
                      f"(Act: {q.get('actual_eps')} vs Est: {q.get('estimated_eps')}, "
                      f"Surprise: {q.get('surprise_pct')}%)")

        # Insider trading
        it = context.get("insider_trading", {}).get(ticker, {})
        if "error" not in it:
            print(f"\n  🏦 INSIDER TRADING:")
            print(f"     Signal      : {it.get('signal')}")
            print(f"     Last 30d    : {it.get('recent_filings_30d', 0)} Form 4 filings")
            print(f"     Last 90d    : {it.get('recent_filings_90d', 0)} Form 4 filings")
            print(f"     Latest      : {it.get('latest_filing_date', 'N/A')}")

    print("\n" + "=" * 65)


# ── Quick test ─────────────────────────────────────────────
if __name__ == "__main__":
    test_tickers = ["AAPL", "NVDA", "TSLA"]
    context = get_market_context(test_tickers)
    print_market_context(context, test_tickers)
