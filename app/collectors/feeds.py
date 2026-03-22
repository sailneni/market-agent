import os, json, requests
from datetime import datetime
import feedparser
from config import NEWS_API_KEY, MARKETAUX_API_KEY, NEWSDATA_API_KEY, BASE_DIR

SEEN_FILE = os.path.join(BASE_DIR, "seen_articles.json")
MIN_LENGTH = 200

RSS_FEEDS = [
    {"name": "Reuters Business",  "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "CNBC Markets",      "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "MarketWatch",       "url": "https://feeds.marketwatch.com/marketwatch/topstories"},
    {"name": "Yahoo Finance",     "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "Seeking Alpha",     "url": "https://seekingalpha.com/feed.xml"},
    {"name": "Investing.com",     "url": "https://www.investing.com/rss/news.rss"},
    {"name": "Moneycontrol",      "url": "https://www.moneycontrol.com/rss/latestnews.xml"},
    {"name": "Economic Times",    "url": "https://economictimes.indiatimes.com/rssfeedstopstories.cms"},
    {"name": "Business Standard", "url": "https://www.business-standard.com/rss/home"},
]

FINANCE_KEYWORDS = [
    "stock", "market", "invest", "bull", "bear", "rally", "crash",
    "earnings", "revenue", "profit", "loss", "fed", "inflation",
    "interest rate", "gold", "silver", "oil", "crypto", "bitcoin",
    "nasdaq", "s&p", "dow", "recession", "gdp", "cpi", "jobs",
    "ipo", "acquisition", "merger", "dividend", "etf", "index fund",
    "xeqt", "smh", "qqq", "spy", "vdy", "semiconductor", "tsx",
]


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def _is_relevant(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in FINANCE_KEYWORDS)


def _make_article(id_, title, body, url, source, published_at, type_) -> dict:
    return {
        "id":           id_,
        "title":        title,
        "body":         body[:3000],
        "url":          url,
        "source":       source,
        "published_at": published_at,
        "type":         type_,
    }


def fetch_rss(max_per_feed: int = 5) -> list:
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:max_per_feed]:
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                body    = f"{title}. {summary}"
                if len(body) < MIN_LENGTH or not _is_relevant(body):
                    continue
                articles.append(_make_article(
                    id_=entry.get("link", title),
                    title=title, body=body,
                    url=entry.get("link", ""),
                    source=feed_info["name"],
                    published_at=entry.get("published", datetime.now().isoformat()),
                    type_="rss",
                ))
        except Exception as e:
            print(f"  ⚠️  RSS failed ({feed_info['name']}): {e}")
    return articles


def fetch_newsapi(max_results: int = 20) -> list:
    if not NEWS_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"category": "business", "language": "en",
                    "pageSize": max_results, "apiKey": NEWS_API_KEY},
            timeout=10,
        ).json()
        articles = []
        for item in resp.get("articles", []):
            title = item.get("title", "")
            desc  = item.get("description", "")
            body  = f"{title}. {desc}".strip()
            if len(body) < MIN_LENGTH or not _is_relevant(body):
                continue
            articles.append(_make_article(
                id_=item.get("url", title),
                title=title, body=body,
                url=item.get("url", ""),
                source=item.get("source", {}).get("name", "NewsAPI"),
                published_at=item.get("publishedAt", datetime.now().isoformat()),
                type_="newsapi",
            ))
        return articles
    except Exception as e:
        print(f"  ❌ NewsAPI failed: {e}")
        return []


def fetch_all() -> list:
    all_articles = fetch_rss() + fetch_newsapi()
    print(f"  📰 Fetched {len(all_articles)} articles total")
    return all_articles
