import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"


def get_ticker_news(ticker: str, company: str = "", days_back: int = 7) -> list:
    """Fetch recent news headlines for a ticker or company name."""
    try:
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        query = f"{ticker} OR {company}" if company else ticker

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": 10,
            "apiKey": NEWS_API_KEY
        }

        response = requests.get(NEWS_API_URL, params=params)
        data = response.json()

        if data.get("status") != "ok":
            return [{"error": data.get("message", "Unknown error")}]

        articles = []
        for article in data.get("articles", []):
            articles.append({
                "title": article.get("title", ""),
                "source": article.get("source", {}).get("name", "Unknown"),
                "published_at": article.get("publishedAt", ""),
                "url": article.get("url", ""),
                "description": article.get("description", "")
            })

        return articles

    except Exception as e:
        return [{"error": str(e)}]


def get_market_news(topics: list = None, days_back: int = 3) -> list:
    """Fetch general market news for given topics."""
    try:
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        if not topics:
            topics = ["stock market", "S&P 500", "Federal Reserve", "inflation"]

        query = " OR ".join(f'"{t}"' for t in topics[:4])

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 10,
            "apiKey": NEWS_API_KEY
        }

        response = requests.get(NEWS_API_URL, params=params)
        data = response.json()

        if data.get("status") != "ok":
            return [{"error": data.get("message", "Unknown error")}]

        articles = []
        for article in data.get("articles", []):
            articles.append({
                "title": article.get("title", ""),
                "source": article.get("source", {}).get("name", "Unknown"),
                "published_at": article.get("publishedAt", ""),
                "url": article.get("url", ""),
                "description": article.get("description", "")
            })

        return articles

    except Exception as e:
        return [{"error": str(e)}]


def score_sentiment(articles: list) -> dict:
    """Simple keyword-based sentiment scoring of headlines."""
    bullish_keywords = [
        "surge", "rally", "gain", "beat", "record", "growth",
        "upgrade", "buy", "outperform", "strong", "rise", "jump",
        "profit", "revenue", "positive", "bullish", "high"
    ]
    bearish_keywords = [
        "fall", "drop", "loss", "miss", "decline", "cut", "downgrade",
        "sell", "underperform", "weak", "crash", "risk", "concern",
        "negative", "bearish", "low", "warn", "fear", "recession"
    ]

    bull_score = 0
    bear_score = 0

    for article in articles:
        title = (article.get("title") or "").lower()
        desc = (article.get("description") or "").lower()
        text = title + " " + desc

        bull_score += sum(1 for kw in bullish_keywords if kw in text)
        bear_score += sum(1 for kw in bearish_keywords if kw in text)

    total = bull_score + bear_score
    if total == 0:
        return {"sentiment": "neutral", "bull_score": 0, "bear_score": 0}

    if bull_score > bear_score * 1.3:
        sentiment = "bullish"
    elif bear_score > bull_score * 1.3:
        sentiment = "bearish"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "bull_pct": round(bull_score / total * 100),
        "bear_pct": round(bear_score / total * 100)
    }


def get_ticker_news_with_sentiment(ticker: str, company: str = "") -> dict:
    """Get news + sentiment score for a ticker in one call."""
    articles = get_ticker_news(ticker, company)
    sentiment = score_sentiment(articles)
    return {
        "ticker": ticker,
        "articles": articles,
        "news_sentiment": sentiment
    }


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("📰 Testing NewsAPI...\n")

    result = get_ticker_news_with_sentiment("AAPL", "Apple")

    print(f"Ticker: {result['ticker']}")
    print(f"News Sentiment: {result['news_sentiment']}")
    print(f"\nLatest Headlines:")
    for a in result["articles"][:5]:
        if "error" not in a:
            print(f"  • [{a['source']}] {a['title']}")
            print(f"    {a['published_at'][:10]} — {a['url']}")