from app.utils import anthropic_client as _client, parse_llm_json


def extract_tickers(text: str) -> list:
    """Extract tickers using Claude Haiku (fast + cheap)."""
    try:
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    "Extract all stock tickers, ETFs, and commodities mentioned.\n"
                    "Return JSON only: "
                    "{\"tickers\": [{\"ticker\": \"NVDA\", \"company\": \"NVIDIA\", \"context\": \"mentioned as AI play\"}]}\n"
                    "Rules:\n"
                    "- Use GOLD for gold mentions, SILVER for silver mentions\n"
                    "- Use real ticker symbols (NVDA not NVIDIA)\n"
                    "- Only include clearly mentioned tickers, no guesses\n\n"
                    f"Text: {text[:8000]}"
                ),
            }],
        )
        return parse_llm_json(msg.content[0].text).get("tickers", [])
    except Exception as e:
        print(f"  ⚠️  Ticker extraction failed: {e}")
        return []
