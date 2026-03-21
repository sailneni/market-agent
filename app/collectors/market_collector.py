import finnhub
from app.config import settings

client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)

def get_quote(ticker: str) -> dict:
    """Get current price and basic metrics."""
    quote = client.quote(ticker)
    return {
        "ticker": ticker,
        "price": quote.get("c"),
        "change_pct": quote.get("dp"),
        "high": quote.get("h"),
        "low": quote.get("l"),
    }

def get_news_sentiment(ticker: str) -> list:
    """Get recent news headlines and sentiment for a ticker."""
    news = client.company_news(ticker, _from="2026-03-01", to="2026-03-19")
    return [
        {
            "headline": n.get("headline"),
            "source": n.get("source"),
            "sentiment": n.get("sentiment", "neutral"),
            "url": n.get("url")
        }
        for n in news[:10]
    ]
