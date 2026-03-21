from youtube_transcript_api import YouTubeTranscriptApi
from news_collector import get_ticker_news_with_sentiment
from technical_indicators import get_technical_indicators
from market_context import get_market_context
from prediction_tracker import log_prediction, evaluate_predictions, get_accuracy_stats, get_model_memory
from db_writer import save_report_to_db  # ✅ NEW
import anthropic
import finnhub
import requests
import json
import re
import os
import time
import glob
import subprocess
import http.cookiejar
import random
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build


load_dotenv()


BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
REPORTS_DIR      = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


SEC_HEADERS      = {"User-Agent": "MarketAgent marketagent@email.com"}
SEEN_VIDEOS_FILE = os.path.join(BASE_DIR, "seen_videos.json")
COOKIES_FILE     = os.path.join(BASE_DIR, "cookies.txt")


COMMODITY_TICKERS = {
    "GOLD":   "GC=F",
    "SILVER": "SI=F",
    "XAU":    "GC=F",
    "XAG":    "SI=F",
    "GLD":    "GLD",
    "SLV":    "SLV",
    "SVR.TO": "SVR.TO",
}

COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}
SKIP_TECHNICALS    = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}

ETF_TICKERS = {
    "XEQT", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU"
}


def ticker_display_icon(ticker):
    t = ticker.upper()
    if t in {"GOLD", "XAU"}:
        return "🥇"
    if t in {"SILVER", "XAG"}:
        return "🥈"
    if t in ETF_TICKERS:
        return "📦"
    return "📈"


def load_seen_videos():
    if os.path.exists(SEEN_VIDEOS_FILE):
        with open(SEEN_VIDEOS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_videos(seen):
    with open(SEEN_VIDEOS_FILE, "w") as f:
        json.dump(list(seen), f)


def get_latest_videos(channel_id, max_results=5):
    try:
        youtube = build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=max_results,
            order="date",
            type="video"
        )
        response = request.execute()
        videos = []
        for item in response.get("items", []):
            videos.append({
                "video_id":     item["id"]["videoId"],
                "title":        item["snippet"]["title"],
                "channel":      item["snippet"]["channelTitle"],
                "published_at": item["snippet"]["publishedAt"]
            })
        return videos
    except Exception as e:
        print(f"  ❌ YouTube API Error: {e}")
        return []


def get_transcript(video_id):
    time.sleep(random.uniform(3, 8))
    try:
        session = requests.Session()
        if os.path.exists(COOKIES_FILE):
            cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        ytt_api = YouTubeTranscriptApi(http_client=session)
        fetched = ytt_api.fetch(video_id)
        print(f"  ✅ Transcript fetched via YouTubeTranscriptApi")
        return " ".join([t.text for t in fetched])
    except Exception as e1:
        print(f"  ⚠️  YouTubeTranscriptApi failed — trying yt-dlp... ({e1})")

    try:
        url      = f"https://www.youtube.com/watch?v={video_id}"
        tmp_path = os.path.join(BASE_DIR, f"tmp_{video_id}")
        cmd = [
            "yt-dlp", "--write-auto-sub", "--sub-lang", "en",
            "--skip-download", "--sub-format", "vtt",
            "-o", tmp_path, "--quiet",
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)
        subprocess.run(cmd, capture_output=True, timeout=30)
        matches = glob.glob(f"{tmp_path}*.vtt")
        if not matches:
            print(f"  ⚠️  yt-dlp found no subtitle file for {video_id}")
            return ""
        with open(matches[0], "r", encoding="utf-8") as f:
            lines = f.readlines()
        os.remove(matches[0])
        text_lines = [
            l.strip() for l in lines
            if l.strip()
            and "WEBVTT" not in l
            and "NOTE"   not in l
            and "-->"    not in l
            and not l.strip().isdigit()
        ]
        transcript = " ".join(text_lines)
        transcript = re.sub(r'\b(\w+)( \1\b)+', r'\1', transcript)
        print(f"  ✅ Transcript fetched via yt-dlp")
        return transcript
    except Exception as e2:
        print(f"  ⚠️  yt-dlp fallback also failed: {e2}")
        return ""


def clean_json(raw):
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return match.group(0).strip()
    return raw.strip()


def analyze_with_claude(transcript, price_map=None, news_map=None, tech_map=None, memory_map=None):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    price_section  = f"\nCURRENT PRICE DATA:\n{json.dumps(price_map, indent=2)}\n"   if price_map  else ""
    tech_section   = f"\nTECHNICAL INDICATORS:\n{json.dumps(tech_map, indent=2)}\n"  if tech_map   else ""
    memory_section = f"\nMODEL PREDICTION HISTORY:\n{json.dumps(memory_map, indent=2)}\n" if memory_map else ""

    news_section = ""
    if news_map:
        slim_news = {
            ticker: {
                "news_sentiment": data.get("news_sentiment", {}),
                "headlines": [a.get("title") for a in data.get("articles", [])[:3]]
            }
            for ticker, data in news_map.items()
        }
        news_section = f"\nRECENT NEWS SENTIMENT:\n{json.dumps(slim_news, indent=2)}\n"

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=(
            "You are a professional investment analyst with access to real-time market data. "
            "Use ALL provided context — transcript, price data, news sentiment, technical indicators, "
            "and prediction history — to produce the most accurate analysis possible. "
            "Return only valid JSON, no markdown."
        ),
        messages=[{
            "role": "user",
            "content": (
                "Analyze the following and return a JSON object with:\n"
                "- tickers: list of {ticker, company, sentiment, context, conviction}\n"
                "  where conviction is low/medium/high based on signal agreement\n"
                "  NOTE: For gold mentions use ticker='GOLD', for silver use ticker='SILVER'\n"
                "  NOTE: Detect ETFs as well — e.g. XEQT, SMH, QQQ, SPY, VDY, SIL, CHPS, GLD, SLV\n"
                "        For ETFs set company name as the ETF full name (e.g. 'iShares Core Equity ETF')\n"
                "  Include gold/silver/ETFs if mentioned even without explicit ticker symbols\n"
                "- key_themes: list of main topics discussed\n"
                "- bull_cases: list of bullish arguments\n"
                "- bear_cases: list of risks mentioned\n"
                "- investment_tactics: list of strategies suggested\n"
                "- overall_market_sentiment: bullish/bearish/neutral\n"
                "- confidence_score: 0.0 to 1.0\n\n"
                f"TRANSCRIPT:\n{transcript[:10000]}\n"
                f"{price_section}{news_section}{tech_section}{memory_section}"
            )
        }]
    )
    return json.loads(clean_json(message.content[0].text))


def get_commodity_price_data(ticker):
    try:
        yf_symbol = COMMODITY_TICKERS.get(ticker.upper(), ticker)
        asset = yf.Ticker(yf_symbol)
        hist  = asset.history(period="2d")
        if hist.empty:
            return {"error": "No data returned"}
        current_price = round(float(hist["Close"].iloc[-1]), 2)
        prev_price    = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else current_price
        change_pct    = round(((current_price - prev_price) / prev_price) * 100, 2)
        return {
            "current_price": current_price,
            "change_pct":    change_pct,
            "high_today":    round(float(hist["High"].iloc[-1]), 2),
            "low_today":     round(float(hist["Low"].iloc[-1]),  2),
            "industry":      "Commodity",
            "currency":      "USD",
            "asset_type":    "commodity"
        }
    except Exception as e:
        return {"error": str(e)}


def get_etf_price_data(ticker):
    try:
        asset = yf.Ticker(ticker)
        info  = asset.info
        hist  = asset.history(period="2d")
        if hist.empty:
            return {"error": "No data returned"}
        current_price = round(float(hist["Close"].iloc[-1]), 2)
        prev_price    = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else current_price
        change_pct    = round(((current_price - prev_price) / prev_price) * 100, 2)
        return {
            "current_price": current_price,
            "change_pct":    change_pct,
            "high_today":    round(float(hist["High"].iloc[-1]), 2),
            "low_today":     round(float(hist["Low"].iloc[-1]),  2),
            "industry":      info.get("category", "ETF"),
            "market_cap":    info.get("totalAssets", 0),
            "currency":      info.get("currency", "USD"),
            "asset_type":    "etf"
        }
    except Exception as e:
        return {"error": str(e)}


def get_price_data(ticker):
    if ticker.upper() in COMMODITY_KEYWORDS:
        return get_commodity_price_data(ticker)
    if ticker.upper() in ETF_TICKERS:
        return get_etf_price_data(ticker)
    try:
        client  = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))
        quote   = client.quote(ticker)
        profile = client.company_profile2(symbol=ticker)
        return {
            "current_price": quote.get("c", 0),
            "change_pct":    round(quote.get("dp", 0), 2),
            "high_today":    quote.get("h", 0),
            "low_today":     quote.get("l", 0),
            "industry":      profile.get("finnhubIndustry", "N/A"),
            "market_cap":    profile.get("marketCapitalization", 0),
            "currency":      profile.get("currency", "USD"),
            "asset_type":    "stock"
        }
    except Exception as e:
        return {"error": str(e)}


def get_sec_data(ticker):
    if ticker.upper() in COMMODITY_KEYWORDS:
        return {"skipped": "Commodity — no SEC filings"}
    if ticker.upper() in ETF_TICKERS:
        return {"skipped": "ETF — no SEC filings"}
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS
        ).json()
        cik = None
        for entry in resp.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break
        if not cik:
            return {"error": "Not found"}
        data   = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS).json()
        recent = data.get("filings", {}).get("recent", {})
        forms  = recent.get("form", [])
        dates  = recent.get("filingDate", [])
        latest_10k = None
        latest_10q = None
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


def save_report(video, analysis, price_map, sec_map, news_map=None, tech_map=None, market_ctx=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"{video['video_id']}_{timestamp}.json"
    filepath  = os.path.join(REPORTS_DIR, filename)

    report = {
        "analyzed_at":    timestamp,
        "video":          video,
        "analysis":       analysis,
        "price_data":     price_map,
        "sec_data":       sec_map,
        "news_data":      news_map   or {},
        "tech_data":      tech_map   or {},
        "market_context": market_ctx or {},
        "_filename":      filename   # ✅ Required by db_writer
    }

    # ── 1. Save JSON backup ───────────────────────────
    try:
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  💾 JSON backup → {filename}")
    except Exception as e:
        print(f"  ⚠️  JSON backup failed: {e}")

    # ── 2. Save to Supabase ───────────────────────────
    try:
        if save_report_to_db(report):
            print(f"  🗄️  Saved → Supabase DB")
        else:
            print(f"  ⚠️  DB save failed (JSON backup exists)")
    except Exception as e:
        print(f"  ⚠️  DB save error (JSON backup exists): {e}")

    return filepath


def print_alert(video, analysis, news_map=None, tech_map=None, market_ctx=None):
    print("\n" + "🔔" * 30)
    print(f"  NEW CONTENT DETECTED & ANALYZED!")
    print(f"  📺 Title     : {video['title']}")
    print(f"  📡 Channel   : {video['channel']}")
    print(f"  🕐 Published : {video['published_at']}")
    print(f"\n  📈 Sentiment : {analysis.get('overall_market_sentiment', 'N/A').upper()}")
    print(f"  🎯 Confidence: {analysis.get('confidence_score', 0) * 100:.0f}%")

    if market_ctx:
        fg = market_ctx.get("fear_and_greed", {})
        if "error" not in fg:
            print(f"  😨 Fear/Greed : {fg.get('score')}/100 — {fg.get('rating', '').upper()}")

    tickers = analysis.get("tickers", [])
    if tickers:
        print(f"\n  📌 Tickers Mentioned:")
        for t in tickers:
            ticker      = t.get("ticker", "")
            icon        = ticker_display_icon(ticker)
            video_sent  = t.get("sentiment", "neutral").upper()
            conviction  = t.get("conviction", "N/A").upper()
            news        = (news_map or {}).get(ticker, {})
            news_sent   = news.get("news_sentiment", {}).get("sentiment", "N/A").upper()
            tech        = (tech_map or {}).get(ticker, {})
            tech_ok     = tech and "error" not in tech and "skipped" not in tech
            tech_signal = tech.get("overall_signal", "N/A") if tech_ok else "N/A"
            rsi_val     = tech.get("rsi", {}).get("value", "N/A") if tech_ok else "N/A"

            print(f"     • {icon} {ticker} ({t.get('company')}) — Conviction: {conviction}")
            print(f"       Video: {video_sent} | News: {news_sent} | Tech: {tech_signal} | RSI: {rsi_val}")

            is_stock = ticker.upper() not in COMMODITY_KEYWORDS and ticker.upper() not in ETF_TICKERS
            if market_ctx and is_stock:
                ec = market_ctx.get("earnings_calendar", {}).get(ticker, {})
                if "error" not in ec and "status" not in ec:
                    print(f"       📅 Earnings: {ec.get('date')} ({ec.get('urgency')})")
                it = market_ctx.get("insider_trading", {}).get(ticker, {})
                if "error" not in it:
                    print(f"       🏦 Insider: {it.get('signal')}")

            for article in news.get("articles", [])[:2]:
                if "error" not in article:
                    print(f"       📰 [{article.get('source')}] {article.get('title', '')[:55]}")

    tactics = analysis.get("investment_tactics", [])
    print(f"\n  💡 Top Tactic: {tactics[0] if tactics else 'No specific tactic mentioned'}")
    print("🔔" * 30 + "\n")


def process_video(video):
    print(f"\n⚙️  Processing: {video['title']}")
    print("  🧠 Evaluating past predictions...")
    evaluate_predictions()
    stats = get_accuracy_stats()
    if stats:
        print(f"  📊 Model accuracy: {stats['accuracy']}% ({stats['correct']}/{stats['total']} correct)")

    transcript = get_transcript(video["video_id"])
    if not transcript:
        print("  ⚠️  No transcript available — skipping.")
        return

    print("  🤖 First pass analysis...")
    first_pass  = analyze_with_claude(transcript)
    tickers_raw = first_pass.get("tickers", [])

    print("  📡 Fetching market data...")
    price_map, news_map, tech_map, sec_map, memory_map = {}, {}, {}, {}, {}

    for t in tickers_raw:
        ticker       = t.get("ticker")
        is_commodity = ticker.upper() in COMMODITY_KEYWORDS
        is_etf       = ticker.upper() in ETF_TICKERS

        price_map[ticker]  = get_price_data(ticker)
        sec_map[ticker]    = get_sec_data(ticker)
        memory_map[ticker] = get_model_memory(ticker)
        news_map[ticker]   = get_ticker_news_with_sentiment(ticker, t.get("company", ""))

        if is_commodity or ticker.upper() in SKIP_TECHNICALS:
            tech_map[ticker] = {"skipped": "Raw commodity — no technical indicators"}
        else:
            tech_map[ticker] = get_technical_indicators(ticker)

    print("  🤖 Re-analyzing with full market context...")
    analysis = analyze_with_claude(
        transcript,
        price_map=price_map,
        news_map=news_map,
        tech_map=tech_map,
        memory_map=memory_map
    )

    confidence = analysis.get("confidence_score", 0)
    if confidence < 0.5:
        print(f"  ⚠️  Low confidence ({confidence:.0%}) — saving report but skipping predictions")
        save_report(video, analysis, price_map, sec_map, news_map, tech_map)
        return

    tickers    = [t.get("ticker") for t in analysis.get("tickers", [])]
    stock_only = [t for t in tickers if t.upper() not in COMMODITY_KEYWORDS and t.upper() not in ETF_TICKERS]

    print("  🌍 Fetching market context...")
    market_ctx = get_market_context(stock_only)

    print("  📝 Logging predictions...")
    for t in analysis.get("tickers", []):
        ticker = t.get("ticker")
        price  = price_map.get(ticker, {}).get("current_price", 0)
        log_prediction(
            ticker=ticker,
            sentiment=t.get("sentiment", "neutral"),
            price_at_prediction=price,
            confidence=confidence,
            video_id=video["video_id"],
            video_title=video["title"]
        )

    save_report(video, analysis, price_map, sec_map, news_map, tech_map, market_ctx)
    print_alert(video, analysis, news_map, tech_map, market_ctx)


def run_watcher(interval_minutes=30):
    channel_ids = os.getenv("YOUTUBE_CHANNEL_IDS", "").split(",")
    channel_ids = [c.strip() for c in channel_ids if c.strip()]

    if not channel_ids:
        print("❌ No channel IDs found in .env")
        return

    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        print(f"   🎬 yt-dlp      : ✅ v{result.stdout.strip()}")
    except FileNotFoundError:
        print("   🎬 yt-dlp      : ❌ Not found")

    print(f"   🥇 Commodities : ✅ Gold & Silver enabled")
    print(f"   📦 ETFs        : ✅ ETF tracking enabled")

    stats = get_accuracy_stats()
    if stats:
        print(f"   🧠 Accuracy    : {stats['accuracy']}% ({stats['correct']}/{stats['total']} predictions)")
    else:
        print(f"   🧠 Accuracy    : No predictions logged yet")

    print("=" * 55)
    print("🚀 MARKET INTELLIGENCE WATCHER STARTED")
    print(f"   Monitoring {len(channel_ids)} channel(s) every {interval_minutes} minutes")
    print("=" * 55)

    seen_videos = load_seen_videos()
    check_count = 0

    while True:
        check_count += 1
        print(f"\n🔍 Check #{check_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        new_video_count = 0
        for channel_id in channel_ids:
            print(f"  📡 Checking channel: {channel_id}")
            for video in get_latest_videos(channel_id):
                vid_id = video["video_id"]
                if vid_id not in seen_videos:
                    print(f"  🆕 NEW: {video['title']}")
                    seen_videos.add(vid_id)
                    save_seen_videos(seen_videos)
                    process_video(video)
                    new_video_count += 1
                    time.sleep(10)
                else:
                    print(f"  ✅ Seen: {video['title'][:50]}...")

        if new_video_count == 0:
            print("  😴 No new videos.")

        print(f"\n⏰ Next check in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    run_watcher(interval_minutes=30)
