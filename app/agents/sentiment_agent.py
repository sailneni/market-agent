from app.utils import anthropic_client as _client, parse_llm_json

_VALID_SENTIMENTS  = {"bullish", "bearish", "neutral"}
_VALID_CONVICTIONS = {"low", "medium", "high"}


def analyze(ticker: str, company: str, context_phrase: str,
            price_data: dict, news_data: dict) -> dict:
    """Sentiment analysis per ticker. Uses Haiku for speed in parallel loops."""
    price_summary = (
        f"Current price: ${price_data.get('current_price', 'N/A')}, "
        f"Change: {price_data.get('change_pct', 'N/A')}%"
    )
    news_sent  = news_data.get("news_sentiment", {}).get("sentiment", "N/A")
    headlines  = [a.get("title", "") for a in news_data.get("articles", [])[:3]]

    try:
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Analyze sentiment for {ticker} ({company}).\n"
                    f"Article context: {context_phrase}\n"
                    f"Price data: {price_summary}\n"
                    f"Recent news sentiment: {news_sent}\n"
                    f"Recent headlines: {headlines}\n\n"
                    "Return JSON only:\n"
                    "{\"sentiment\": \"bullish|bearish|neutral\", "
                    "\"conviction\": \"low|medium|high\", "
                    "\"reasoning\": \"one sentence\"}"
                ),
            }],
        )
        raw = parse_llm_json(msg.content[0].text)
        sentiment  = raw.get("sentiment",  "neutral").lower()
        conviction = raw.get("conviction", "medium").lower()
        return {
            "sentiment":  sentiment  if sentiment  in _VALID_SENTIMENTS  else "neutral",
            "conviction": conviction if conviction in _VALID_CONVICTIONS else "medium",
            "reasoning":  raw.get("reasoning", ""),
        }
    except Exception as e:
        print(f"  ⚠️  Sentiment analysis failed for {ticker}: {e}")
        return {"sentiment": "neutral", "conviction": "low", "reasoning": f"Analysis failed: {e}"}
