import requests
from datetime import datetime, timedelta
from config import NEWS_API_KEY

BULL_WORDS = {"buy", "bullish", "rally", "surge", "gain", "beat", "upgrade", "growth", "strong", "positive", "rise"}
BEAR_WORDS = {"sell", "bearish", "drop", "crash", "loss", "miss", "downgrade", "weak", "negative", "cut", "fall"}


def get_news(ticker: str, company: str = "", days_back: int = 7) -> dict:
    """Fetch recent news and score sentiment for a ticker."""
    if not NEWS_API_KEY:
        return {"articles": [], "news_sentiment": {"sentiment": "N/A"}}
    try:
        query    = f"{ticker} OR {company}" if company else ticker
        from_dt  = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        resp     = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query, "from": from_dt,
                "sortBy": "relevancy", "language": "en",
                "pageSize": 10, "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        ).json()
        if resp.get("status") != "ok":
            return {"articles": [], "news_sentiment": {"sentiment": "N/A"}}

        articles = []
        bull = bear = 0
        for a in resp.get("articles", [])[:10]:
            title  = (a.get("title") or "").lower()
            bull  += sum(1 for w in BULL_WORDS if w in title)
            bear  += sum(1 for w in BEAR_WORDS if w in title)
            articles.append({
                "title":        a.get("title", ""),
                "source":       a.get("source", {}).get("name", ""),
                "url":          a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
            })

        sentiment = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
        return {
            "articles":       articles,
            "news_sentiment": {"sentiment": sentiment, "bull_score": bull, "bear_score": bear},
        }
    except Exception as e:
        return {"articles": [], "news_sentiment": {"sentiment": "N/A"}, "error": str(e)}
