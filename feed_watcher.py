import feedparser
import praw
import json
import os
import time
import random
import requests
from datetime import datetime
from dotenv import load_dotenv
from prediction_tracker import log_prediction, evaluate_predictions, get_accuracy_stats, get_model_memory
from watcher import (
    analyze_with_claude, get_price_data, get_sec_data,
    print_alert,
    COMMODITY_KEYWORDS, SKIP_TECHNICALS, ETF_TICKERS
)
from news_collector import get_ticker_news_with_sentiment
from technical_indicators import get_technical_indicators
from market_context import get_market_context
from db_writer import save_report_to_db

load_dotenv()

BASE_DIR           = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
REPORTS_DIR        = os.path.join(BASE_DIR, "reports")
SEEN_ARTICLES_FILE = os.path.join(BASE_DIR, "seen_articles.json")
os.makedirs(REPORTS_DIR, exist_ok=True)


RSS_FEEDS = [
    {"name": "Reuters Business",  "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "CNBC Markets",      "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "MarketWatch",       "url": "https://feeds.marketwatch.com/marketwatch/topstories"},
    {"name": "Yahoo Finance",     "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "Seeking Alpha",     "url": "https://seekingalpha.com/feed.xml"},
    {"name": "Investing.com",     "url": "https://www.investing.com/rss/news.rss"},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss"},
]

SUBREDDITS = [
    "wallstreetbets", "investing", "stocks",
    "SecurityAnalysis", "gold", "Silverbugs",
    "options", "StockMarket", "ETFs"
]

MIN_CONTENT_LENGTH = 200

FINANCE_KEYWORDS = [
    "stock", "market", "invest", "bull", "bear", "rally", "crash",
    "earnings", "revenue", "profit", "loss", "fed", "inflation",
    "interest rate", "gold", "silver", "oil", "crypto", "bitcoin",
    "nasdaq", "s&p", "dow", "recession", "gdp", "cpi", "jobs",
    "ipo", "acquisition", "merger", "dividend",
    "etf", "index fund", "xeqt", "smh", "qqq", "spy", "vdy",
    "semiconductor", "sector etf", "vanguard", "ishares", "invesco",
    "chps", "sil", "silj", "svr", "cash.to", "tsx", "cgl"
]


def load_seen_articles():
    if os.path.exists(SEEN_ARTICLES_FILE):
        with open(SEEN_ARTICLES_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_articles(seen):
    with open(SEEN_ARTICLES_FILE, "w") as f:
        json.dump(list(seen), f)


def is_finance_relevant(text):
    return any(kw in text.lower() for kw in FINANCE_KEYWORDS)


def fetch_rss_articles(max_per_feed=5):
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed  = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries[:max_per_feed]:
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link    = entry.get("link", "")
                content = f"{title}. {summary}"
                if len(content) < MIN_CONTENT_LENGTH or not is_finance_relevant(content):
                    continue
                articles.append({
                    "id":           link,
                    "title":        title,
                    "content":      content,
                    "url":          link,
                    "source":       feed_info["name"],
                    "published_at": entry.get("published", datetime.now().isoformat()),
                    "type":         "rss"
                })
                count += 1
            print(f"  📡 {feed_info['name']}: {count} articles")
        except Exception as e:
            print(f"  ⚠️  RSS failed ({feed_info['name']}): {e}")
    return articles


def fetch_reddit_posts(max_per_sub=5):
    posts      = []
    reddit_id  = os.getenv("REDDIT_CLIENT_ID")
    reddit_sec = os.getenv("REDDIT_CLIENT_SECRET")

    if not reddit_id or not reddit_sec or reddit_id == "your_reddit_client_id":
        print("  ⚠️  Reddit credentials not set — skipping")
        return posts

    try:
        reddit = praw.Reddit(
            client_id=reddit_id,
            client_secret=reddit_sec,
            user_agent="MarketAgent/1.0"
        )
        for sub_name in SUBREDDITS:
            try:
                count = 0
                for post in reddit.subreddit(sub_name).hot(limit=max_per_sub):
                    if post.stickied:
                        continue
                    content = f"{post.title}. {post.selftext or ''}"[:3000]
                    if len(content) < MIN_CONTENT_LENGTH or not is_finance_relevant(content):
                        continue
                    posts.append({
                        "id":           f"reddit_{post.id}",
                        "title":        post.title,
                        "content":      content,
                        "url":          f"https://reddit.com{post.permalink}",
                        "source":       f"r/{sub_name}",
                        "published_at": datetime.fromtimestamp(post.created_utc).isoformat(),
                        "score":        post.score,
                        "comments":     post.num_comments,
                        "type":         "reddit"
                    })
                    count += 1
                print(f"  🤖 r/{sub_name}: {count} posts")
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  r/{sub_name} failed: {e}")
    except Exception as e:
        print(f"  ❌ Reddit init failed: {e}")
    return posts


def fetch_newsapi_articles(max_results=20):
    articles = []
    api_key  = os.getenv("NEWSAPI_KEY")

    if not api_key:
        print("  ⚠️  NEWSAPI_KEY not set — skipping NewsAPI")
        return articles

    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"category": "business", "language": "en", "pageSize": max_results, "apiKey": api_key},
            timeout=10
        ).json()

        for item in resp.get("articles", []):
            title   = item.get("title", "")
            desc    = item.get("description", "")
            content = item.get("content", "")
            full    = f"{title}. {desc} {content}".strip()
            if len(full) < MIN_CONTENT_LENGTH or not is_finance_relevant(full):
                continue
            articles.append({
                "id":           item.get("url", title),
                "title":        title,
                "content":      full[:3000],
                "url":          item.get("url", ""),
                "source":       item.get("source", {}).get("name", "NewsAPI"),
                "published_at": item.get("publishedAt", datetime.now().isoformat()),
                "type":         "newsapi"
            })
        print(f"  📰 NewsAPI: {len(articles)} articles")
    except Exception as e:
        print(f"  ❌ NewsAPI failed: {e}")
    return articles

# ── Bonus: Marketaux for finance-specific news with sentiment! ─────────────────────────────
def fetch_marketaux_articles(max_results=20):
    """Marketaux: Finance-focused with tickers & Canada support"""
    articles = []
    api_key = os.getenv("MARKETAUX_API_KEY")
    
    if not api_key:
        print("  ⚠️  MARKETAUX_API_KEY not set — skipping Marketaux")
        return articles
    
    try:
        resp = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "symbols": "XEQT,SMH,SVR,VDY,SIL,TSX,CGL,CHPS",  # Your ETFs/commodities
                "countries": "ca,us",
                "language": "en",
                "page_size": max_results,
                "api_token": api_key
            },
            timeout=10
        ).json()
        
        data_list = resp.get("data") if isinstance(resp.get("data"), list) else resp.get("data", [])
        
        for item in data_list:
            title = item.get("title", "") if isinstance(item, dict) else ""
            desc = item.get("description", "") if isinstance(item, dict) else ""
            full = f"{title}. {desc}".strip()
            
            if len(full) < MIN_CONTENT_LENGTH or not is_finance_relevant(full):
                continue
                
            articles.append({
                "id": item.get("url", title) if isinstance(item, dict) else title,
                "title": title,
                "content": full[:3000],
                "url": item.get("url", "") if isinstance(item, dict) else "",
                "source": item.get("source", "Marketaux") if isinstance(item, dict) else "Marketaux",
                "published_at": item.get("published_at", datetime.now().isoformat()) if isinstance(item, dict) else datetime.now().isoformat(),
                "type": "marketaux"
            })
        print(f"  💰 Marketaux: {len(articles)} articles")
    except Exception as e:
        print(f"  ❌ Marketaux failed: {e}")
    return articles

#── Bonus: NewsData.io for historical news & strong Canada coverage ─────────────────────────
def fetch_newsdata_articles(max_results=20):
    """NewsData.io: Option 1 - Loose filters for free tier"""
    articles = []
    api_key = os.getenv("NEWSDATA_API_KEY")
    
    if not api_key:
        print("  ⚠️  NEWSDATA_API_KEY not set — skipping")
        return articles
    
    try:
        resp = requests.get(
            "https://newsdata.io/api/1/news",
            params={
                "apikey": api_key,
                "q": "finance OR market OR stock OR ETF OR business OR TSX OR gold",  # Broad hits
                "country": "us,ca",
                "language": "en",
                "size": max_results
            },
            timeout=10
        ).json()
        
        data_list = []
        results = resp.get("results")
        if isinstance(results, list):
            data_list = results
        elif isinstance(results, dict):
            data_list = [results]
            
        print(f"  📊 NewsData: {len(data_list)} raw items")
        
        for item in data_list:
            if not isinstance(item, dict): continue
            
            title = item.get("title", "")
            desc = item.get("description", "")
            full = f"{title}. {desc}".strip()
            
            # Looser for API snippets
            if len(full) < 80 or not is_finance_relevant(full):
                continue
                
            articles.append({
                "id": item.get("link") or item.get("article_id") or title[:50],
                "title": title,
                "content": full[:3000],
                "url": item.get("link", ""),
                "source": str(item.get("source_id") or "NewsData"),
                "published_at": item.get("pubDate") or item.get("date") or datetime.now().isoformat(),
                "type": "newsdata"
            })
        print(f"  🌐 NewsData.io: {len(articles)} articles")
    except Exception as e:
        print(f"  ❌ NewsData.io: {e}")
    return articles


def process_article(article):
    print(f"\n⚙️  [{article['source']}] {article['title'][:70]}")

    if len(article["content"]) < MIN_CONTENT_LENGTH:
        print("  ⚠️  Content too short — skipping.")
        return

    evaluate_predictions()
    stats = get_accuracy_stats()
    if stats:
        print(f"  📊 Accuracy: {stats['accuracy']}% | 📦 ETF: {stats.get('etf_accuracy', 'N/A')}% | 🥇 Commodity: {stats.get('commodity_accuracy', 'N/A')}%")

    print("  🤖 First pass analysis...")
    first_pass  = analyze_with_claude(article["content"])
    tickers_raw = first_pass.get("tickers", [])

    if not tickers_raw:
        print("  ⚠️  No tickers detected — skipping.")
        return

    print(f"  📡 Fetching data for {len(tickers_raw)} tickers...")
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
            tech_map[ticker] = {"skipped": "Commodity — no technical indicators"}
        else:
            tech_map[ticker] = get_technical_indicators(ticker)

    print("  🤖 Re-analyzing with full context...")
    analysis = analyze_with_claude(
        article["content"],
        price_map=price_map,
        news_map=news_map,
        tech_map=tech_map,
        memory_map=memory_map
    )

    confidence = analysis.get("confidence_score", 0)
    if confidence < 0.5:
        print(f"  ⚠️  Low confidence ({confidence:.0%}) — skipping")
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
            video_id=article["id"],
            video_title=f"[{article['source']}] {article['title'][:60]}"
        )

    # ── Build report dict ─────────────────────────────
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_id_clean = article["id"][:50].replace("/", "_").replace(":", "_")
    filename       = f"{video_id_clean}_{timestamp}.json"

    article_as_video = {
        "video_id":     video_id_clean,
        "title":        f"[{article['source']}] {article['title']}",
        "channel":      article["source"],
        "published_at": article["published_at"],
        "url":          article.get("url", ""),
        "type":         article.get("type", "rss")
    }

    report = {
        "analyzed_at":    timestamp,
        "video":          article_as_video,
        "analysis":       analysis,
        "price_data":     price_map,
        "sec_data":       sec_map,
        "news_data":      news_map,
        "tech_data":      tech_map,
        "market_context": market_ctx,
        "_filename":      filename
    }

    # ── 1. Save JSON backup ───────────────────────────
    try:
        json_path = os.path.join(REPORTS_DIR, filename)
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  💾 JSON backup: {filename}")
    except Exception as e:
        print(f"  ⚠️  JSON backup failed: {e}")

    # ── 2. Save to Supabase ───────────────────────────
    if save_report_to_db(report):
        print(f"  ✅ Saved to Supabase: {article['source']} — {article['title'][:50]}")
    else:
        print(f"  ⚠️  Failed to save to Supabase")

    print_alert(article_as_video, analysis, news_map, tech_map, market_ctx)


def run_feed_watcher(interval_minutes=30):
    reddit_enabled  = bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_ID") != "your_reddit_client_id")
    newsapi_enabled = bool(os.getenv("NEWSAPI_KEY"))
    marketaux_enabled = bool(os.getenv("MARKETAUX_API_KEY"))
    newsdata_enabled = bool(os.getenv("NEWSDATA_API_KEY"))

    print("=" * 60)
    print("🚀 FEED WATCHER STARTED (w/ Marketaux + NewsData.io)")
    print(f"   📡 RSS Feeds     : ✅ {len(RSS_FEEDS)} sources")
    print(f"   🤖 Reddit        : {'✅ Enabled' if reddit_enabled else '⚠️  Disabled'}")
    print(f"   📰 NewsAPI       : {'✅ Enabled' if newsapi_enabled else '⚠️  Disabled'}")
    print(f"   💰 Marketaux     : {'✅ Enabled' if marketaux_enabled else '⚠️  Disabled'}")
    print(f"   🌐 NewsData.io   : {'✅ Enabled' if newsdata_enabled else '⚠️  Disabled'}")
    print(f"   📦 ETFs          : ✅ ETF tracking enabled")
    print(f"   🥇 Commodities   : ✅ Gold & Silver enabled")
    print(f"   ⏱️  Interval      : every {interval_minutes} minutes")
    print("=" * 60)

    seen_articles = load_seen_articles()
    check_count   = 0

    while True:
        check_count += 1
        print(f"\n🔍 Feed Check #{check_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        all_articles  = []
        print("\n  📡 Fetching RSS feeds...")
        all_articles += fetch_rss_articles(max_per_feed=5)

        print("\n  🤖 Fetching Reddit posts...")
        all_articles += fetch_reddit_posts(max_per_sub=5)

        print("\n  📰 Fetching NewsAPI articles...")
        all_articles += fetch_newsapi_articles(max_results=20)

        print("\n  💰 Fetching Marketaux articles...")
        all_articles += fetch_marketaux_articles(max_results=20)

        print("\n  🌐 Fetching NewsData.io articles...")
        all_articles += fetch_newsdata_articles(max_results=20)

        print(f"\n  📦 Total fetched: {len(all_articles)} items")

        new_count = 0
        for article in all_articles:
            if article["id"] in seen_articles:
                continue
            seen_articles.add(article["id"])
            save_seen_articles(seen_articles)
            process_article(article)
            new_count += 1
            time.sleep(random.uniform(3, 7))

        print(f"\n  {'✅ Processed ' + str(new_count) + ' new articles.' if new_count else '😴 No new articles.'}")
        print(f"⏰ Next check in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    run_feed_watcher(interval_minutes=30)
