"""
app/utils.py — Shared utilities used across multiple modules.
"""
import re, json
import anthropic
from config import ANTHROPIC_API_KEY

# Single Anthropic client reused by all agents
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# SEC EDGAR shared headers
SEC_HEADERS = {"User-Agent": "MarketAgent marketagent@email.com"}


def parse_llm_json(text: str) -> dict | list:
    """Extract and parse the first JSON object from an LLM response."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)
