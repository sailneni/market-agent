import anthropic
import json
from app.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

def extract_tickers(text: str) -> list:
    """Use Claude to extract stock tickers from transcript."""
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Extract all stock tickers, company names, and ETFs mentioned in this text.
                Return a JSON object like: {{"tickers": [{{"ticker": "NVDA", "company": "NVIDIA", "context": "mentioned as AI play"}}]}}
                
                Text: {text[:10000]}"""
            }
        ]
    )
    raw = message.content[0].text
    return json.loads(raw).get("tickers", [])
