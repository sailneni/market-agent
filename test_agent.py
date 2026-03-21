from youtube_transcript_api import YouTubeTranscriptApi
from news_collector import get_ticker_news_with_sentiment
from technical_indicators import get_technical_indicators
from market_context import get_market_context, print_market_context
import anthropic
import finnhub
import requests
import json
import re
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Force working directory to project root ────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

SEC_HEADERS = {"User-Agent": "MarketAgent marketagent@email.com"}
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")


def get_transcript(video_id):
    print(f"\n📥 Fetching transcript for: {video_id}")
    try:
        if os.path.exists(COOKIES_FILE):
            print(f"  🍪 Using cookies from {COOKIES_FILE}")
            ytt_api = YouTubeTranscriptApi(cookie_path=COOKIES_FILE)
        else:
            print(f"  ⚠️  No cookies.txt found — may hit IP blocks")
            ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id)
        full_text = " ".join([t.text for t in fetched])
        print(f"✅ Got transcript! ({len(full_text)} characters)")
        return full_text
    except Exception as e:
        print(f"❌ Error: {e}")
        return ""


def clean_json(raw):
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return match.group(0).strip()
    return raw.strip()


def analyze_with_claude(transcript):
    print("\n🤖 Sending to Claude for analysis...")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system="You are a professional investment analyst. Return only valid JSON, no markdown.",
        messages=[
            {
                "role": "user",
                "content": (
                    "Analyze this stock market video transcript and return a JSON object with:\n"
                    "- tickers: list of {ticker, company, sentiment, context}\n"
                    "- key_themes: list of main topics discussed\n"
                    "- bull_cases: list of bullish arguments\n"
                    "- bear_cases: list of risks mentioned\n"
                    "- investment_tactics: list of strategies suggested\n"
                    "- overall_market_sentiment: bullish/bearish/neutral\n"
                    "- confidence_score: 0.0 to 1.0\n\n"
                    f"Transcript:\n{transcript[:15000]}"
                )
            }
        ]
    )
    raw = clean_json(message.content[0].text)
    print("✅ Claude analysis done!")
    return json.loads(raw)


def get_price_data(ticker):
    try:
        client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))
        quote = client.quote(ticker)
        profile = client.company_profile2(symbol=ticker)
        return {
            "current_price": quote.get("c", 0),
            "change_pct": round(quote.get("dp", 0), 2),
            "high_today": quote.get("h", 0),
            "low_today": quote.get("l", 0),
            "prev_close": quote.get("pc", 0),
            "industry": profile.get("finnhubIndustry", "N/A"),
            "market_cap": profile.get("marketCapitalization", 0),
            "currency": profile.get("currency", "USD")
        }
    except Exception as e:
        print(f"  ⚠️  Price fetch failed for {ticker}: {e}")
        return {}


def get_sec_data(ticker):
    try:
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        resp = requests.get(tickers_url, headers=SEC_HEADERS).json()
        cik = None
        company_name = None
        for entry in resp.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                company_name = entry["title"]
                break

        if not cik:
            return {"error": f"CIK not found for {ticker}"}

        filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = requests.get(filings_url, headers=SEC_HEADERS).json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])

        latest_10k = None
        latest_10q = None
        for form, date, acc in zip(forms, dates, accessions):
            if form == "10-K" and not latest_10k:
                latest_10k = {"form": form, "date": date, "accession": acc}
            if form == "10-Q" and not latest_10q:
                latest_10q = {"form": form, "date": date, "accession": acc}
            if latest_10k and latest_10q:
                break

        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        facts_resp = requests.get(facts_url, headers=SEC_HEADERS)
        financials = {}

        if facts_resp.status_code == 200:
            facts = facts_resp.json()
            us_gaap = facts.get("facts", {}).get("us-gaap", {})

            for key in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]:
                if key in us_gaap:
                    units = us_gaap[key].get("units", {}).get("USD", [])
                    annual = [u for u in units if u.get("form") == "10-K"]
                    if annual:
                        latest = sorted(annual, key=lambda x: x["end"])[-1]
                        financials["revenue"] = {
                            "value": latest["val"],
                            "period": latest["end"],
                            "label": "Annual Revenue"
                        }
                    break

            for key in ["NetIncomeLoss", "ProfitLoss"]:
                if key in us_gaap:
                    units = us_gaap[key].get("units", {}).get("USD", [])
                    annual = [u for u in units if u.get("form") == "10-K"]
                    if annual:
                        latest = sorted(annual, key=lambda x: x["end"])[-1]
                        financials["net_income"] = {
                            "value": latest["val"],
                            "period": latest["end"],
                            "label": "Annual Net Income"
                        }
                    break

            for key in ["EarningsPerShareBasic", "EarningsPerShareDiluted"]:
                if key in us_gaap:
                    units = us_gaap[key].get("units", {}).get("USD/shares", [])
                    annual = [u for u in units if u.get("form") == "10-K"]
                    if annual:
                        latest = sorted(annual, key=lambda x: x["end"])[-1]
                        financials["eps"] = {
                            "value": latest["val"],
                            "period": latest["end"],
                            "label": "EPS (Diluted)"
                        }
                    break

        return {
            "cik": cik,
            "company_name": company_name,
            "latest_10k": latest_10k,
            "latest_10q": latest_10q,
            "financials": financials
        }

    except Exception as e:
        return {"error": str(e)}


def generate_tactic(sentiment, change_pct, sec_data, news_sentiment="neutral", tech_data=None):
    try:
        change = float(change_pct)
    except Exception:
        return "WATCH — price data unavailable"

    financials = sec_data.get("financials", {})
    net_income = financials.get("net_income", {}).get("value", None)
    fundamental = "profitable" if net_income and net_income > 0 else "unprofitable" if net_income else "unknown"

    signals = [sentiment, news_sentiment]
    tech_signal = "neutral"
    if tech_data and "overall_signal" in tech_data:
        sig = tech_data["overall_signal"].lower()
        if "strong buy" in sig or "buy" in sig:
            tech_signal = "bullish"
        elif "strong sell" in sig or "sell" in sig:
            tech_signal = "bearish"
    signals.append(tech_signal)

    bullish_count = signals.count("bullish")
    bearish_count = signals.count("bearish")

    if bullish_count == 3:
        combined = "strongly bullish"
    elif bullish_count == 2:
        combined = "leaning bullish"
    elif bearish_count == 3:
        combined = "strongly bearish"
    elif bearish_count == 2:
        combined = "leaning bearish"
    else:
        combined = "mixed"

    if "bullish" in combined:
        if change < -3:
            return f"BUY — {combined} signals + dip opportunity ({fundamental})"
        elif change > 5:
            return f"HOLD — {combined} but wait for pullback ({fundamental})"
        else:
            return f"BUY/HOLD — {combined} momentum ({fundamental})"
    elif "bearish" in combined:
        return f"SELL/AVOID — {combined} signals ({fundamental})"
    else:
        return f"WATCH — {combined} signals ({fundamental})"


def fmt(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.2f}"


def print_report(analysis, price_map, sec_map, news_map=None, tech_map=None, market_ctx=None):
    print("\n" + "=" * 65)
    print("📊  MARKET INTELLIGENCE REPORT")
    print("=" * 65)

    # ── Fear & Greed ───────────────────────────────────────
    if market_ctx:
        fg = market_ctx.get("fear_and_greed", {})
        if "error" not in fg:
            print(f"\n😨 FEAR & GREED : {fg.get('score')}/100 — {fg.get('signal')}")

    print("\n📌 TICKERS — LIVE PRICE + SEC + NEWS + TECHNICALS:")
    print("-" * 65)

    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        sentiment = t.get("sentiment", "neutral").lower()
        context = t.get("context", "")
        price = price_map.get(ticker, {})
        sec = sec_map.get(ticker, {})
        financials = sec.get("financials", {})
        news = (news_map or {}).get(ticker, {})
        news_sentiment_data = news.get("news_sentiment", {})
        news_sentiment = news_sentiment_data.get("sentiment", "neutral")
        tech = (tech_map or {}).get(ticker, {})

        current_price = price.get("current_price", "N/A")
        change_pct = price.get("change_pct", "N/A")
        high = price.get("high_today", "N/A")
        low = price.get("low_today", "N/A")
        industry = price.get("industry", "N/A")
        mktcap = price.get("market_cap", 0)
        currency = price.get("currency", "USD")

        revenue = financials.get("revenue", {})
        net_income = financials.get("net_income", {})
        eps = financials.get("eps", {})
        latest_10k = sec.get("latest_10k", {})
        latest_10q = sec.get("latest_10q", {})

        change_arrow = "🔺" if isinstance(change_pct, float) and change_pct > 0 else "🔻"
        tactic = generate_tactic(sentiment, change_pct, sec, news_sentiment, tech)

        print(f"\n  🏷️  {ticker} — {t.get('company')}")
        print(f"      Industry     : {industry}")
        print(f"      Price        : {currency} ${current_price}  {change_arrow} {change_pct}% today")
        print(f"      Range Today  : Low ${low}  —  High ${high}")
        if isinstance(mktcap, (int, float)) and mktcap > 0:
            print(f"      Market Cap   : ${mktcap:,.0f}M")

        print(f"\n      📄 SEC FILINGS:")
        if latest_10k:
            print(f"         Latest 10-K : {latest_10k.get('date', 'N/A')}")
        if latest_10q:
            print(f"         Latest 10-Q : {latest_10q.get('date', 'N/A')}")

        print(f"\n      💰 FINANCIALS:")
        if revenue:
            print(f"         Revenue     : {fmt(revenue.get('value'))} ({revenue.get('period', '')})")
        if net_income:
            val = net_income.get("value", 0)
            indicator = "✅ Profitable" if val > 0 else "❌ Loss"
            print(f"         Net Income  : {fmt(val)} — {indicator}")
        if eps:
            print(f"         EPS         : ${eps.get('value', 'N/A')} ({eps.get('period', '')})")

        print(f"\n      📰 NEWS SENTIMENT  : {news_sentiment.upper()}")
        if news_sentiment_data:
            print(f"         Bull Score  : {news_sentiment_data.get('bull_score', 0)}")
            print(f"         Bear Score  : {news_sentiment_data.get('bear_score', 0)}")
        articles = news.get("articles", [])
        if articles:
            print(f"\n      🗞️  LATEST HEADLINES:")
            for article in articles[:3]:
                if "error" not in article:
                    print(f"         • [{article.get('source', 'N/A')}] {article.get('title', '')[:65]}")

        if tech and "error" not in tech:
            print(f"\n      📊 TECHNICALS:")
            print(f"         Signal      : {tech.get('overall_signal', 'N/A')}")
            print(f"         RSI (14)    : {tech.get('rsi', {}).get('value', 'N/A')}")
            print(f"         MACD        : {tech.get('macd', {}).get('crossover', 'N/A').upper()}")
            print(f"         Trend       : {tech.get('trend', {}).get('trend', 'N/A')}")
            sr = tech.get("support_resistance", {})
            print(f"         Support     : ${sr.get('support', 'N/A')} | Resistance: ${sr.get('resistance', 'N/A')}")

        # ── Market context per ticker ──────────────────────
        if market_ctx:
            ec = market_ctx.get("earnings_calendar", {}).get(ticker, {})
            if "error" not in ec and "status" not in ec:
                print(f"\n      📅 NEXT EARNINGS  : {ec.get('date')} ({ec.get('urgency')}) — EPS Est: {ec.get('eps_estimate', 'N/A')}")

            eh = market_ctx.get("earnings_history", {}).get(ticker, {})
            if "error" not in eh:
                print(f"      📊 BEAT RATE      : {eh.get('beat_rate')} quarters {'✅ Consistent' if eh.get('consistent_beater') else '❌ Inconsistent'}")

            it = market_ctx.get("insider_trading", {}).get(ticker, {})
            if "error" not in it:
                print(f"      🏦 INSIDER        : {it.get('signal')}")

        print(f"\n      📰 Video Context : {context}")
        print(f"      🎯 Video Sent.   : {sentiment.upper()}")
        print(f"      💡 Tactic        : {tactic}")
        print()

    print("-" * 65)

    print("\n🔑 KEY THEMES:")
    for theme in analysis.get("key_themes", []):
        print(f"  • {theme}")

    print("\n🟢 BULL CASES:")
    for bull in analysis.get("bull_cases", []):
        print(f"  • {bull}")

    print("\n🔴 BEAR CASES:")
    for bear in analysis.get("bear_cases", []):
        print(f"  • {bear}")

    print("\n💡 INVESTMENT TACTICS:")
    for tactic in analysis.get("investment_tactics", []):
        print(f"  • {tactic}")

    sentiment = analysis.get("overall_market_sentiment", "N/A").upper()
    confidence = analysis.get("confidence_score", 0) * 100
    print(f"\n📈 OVERALL SENTIMENT : {sentiment}")
    print(f"🎯 CONFIDENCE SCORE  : {confidence:.0f}%")
    print("=" * 65)


if __name__ == "__main__":
    VIDEO_ID = "bqPSFw1eiNc"

    # ── Cookies status ─────────────────────────────────────
    if os.path.exists(COOKIES_FILE):
        print(f"🍪 Cookies: ✅ Loaded ({COOKIES_FILE})")
    else:
        print(f"🍪 Cookies: ⚠️  Not found — add cookies.txt to avoid IP blocks")

    transcript = get_transcript(VIDEO_ID)
    if not transcript:
        print("❌ Could not get transcript.")
        exit()

    analysis = analyze_with_claude(transcript)
    tickers = [t.get("ticker") for t in analysis.get("tickers", [])]

    print("\n📡 Fetching live prices...")
    price_map = {}
    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        print(f"  → {ticker}...")
        price_map[ticker] = get_price_data(ticker)

    print("\n📄 Fetching SEC EDGAR filings...")
    sec_map = {}
    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        print(f"  → {ticker}...")
        sec_map[ticker] = get_sec_data(ticker)

    print("\n📰 Fetching news headlines...")
    news_map = {}
    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        company = t.get("company", "")
        print(f"  → {ticker}...")
        news_map[ticker] = get_ticker_news_with_sentiment(ticker, company)

    print("\n📊 Fetching technical indicators...")
    tech_map = {}
    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        print(f"  → {ticker}...")
        tech_map[ticker] = get_technical_indicators(ticker)

    market_ctx = get_market_context(tickers)

    print_report(analysis, price_map, sec_map, news_map, tech_map, market_ctx)

    output = {
        "video": {
            "video_id": VIDEO_ID,
            "title": "Manual Test Analysis",
            "channel": "Manual",
            "published_at": datetime.now().isoformat()
        },
        "analyzed_at": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "video_id": VIDEO_ID,
        "analysis": analysis,
        "price_data": price_map,
        "sec_data": sec_map,
        "news_data": news_map,
        "tech_data": tech_map,
        "market_context": market_ctx
    }

    with open(os.path.join(BASE_DIR, "analysis_result.json"), "w") as f:
        json.dump(output, f, indent=2)
    print("\n💾 Saved to → analysis_result.json")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"{VIDEO_ID}_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"💾 Saved to → {report_path}")
    print(f"\n✅ Dashboard will now show this report!")
