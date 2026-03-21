import anthropic
import json
from app.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

def generate_tactic(ticker: str, signals: list, price_data: dict) -> dict:
    """Generate structured investment tactic using Claude."""
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        system="You are a professional investment analyst. Be factual, neutral, and risk-aware. Always highlight risks clearly.",
        messages=[
            {
                "role": "user",
                "content": f"""
                Analyze this ticker and provide an investment tactic.

                Ticker: {ticker}
                Current Price: {price_data.get('price')} | Change: {price_data.get('change_pct')}%
                
                Signals collected:
                {json.dumps(signals, indent=2)}

                Return a JSON object with:
                - bull_case (string)
                - bear_case (string)
                - overall_sentiment (bullish/bearish/neutral)
                - conviction (low/medium/high)
                - tactic (buy/hold/sell/watch)
                - entry_suggestion (string)
                - stop_loss_suggestion (string)
                - risk_level (1-10)
                - what_would_invalidate (string)
                """
            }
        ]
    )
    raw = message.content[0].text
    return json.loads(raw)
