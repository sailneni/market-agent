import anthropic
import json
from app.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

def analyze_sentiment(text: str, ticker: str) -> dict:
    """Analyze sentiment of a transcript or article for a specific ticker."""
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""Analyze the sentiment toward {ticker} in this text.
                Return JSON: {{"sentiment": "bullish/bearish/neutral", "score": 0.0-1.0, "key_points": ["point1", "point2"], "risks_mentioned": ["risk1"]}}
                
                Text: {text[:8000]}"""
            }
        ]
    )
    return json.loads(message.content[0].text)
