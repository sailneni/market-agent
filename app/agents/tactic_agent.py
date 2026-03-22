from app.utils import anthropic_client as _client, parse_llm_json

_EMPTY = {"bull_cases": [], "bear_cases": [], "entry_zone": "N/A",
          "stop_loss": "N/A", "targets": [], "tactics": [],
          "time_horizon": "N/A", "key_risks": [], "themes": []}


def generate(
    ticker: str,
    company: str,
    sentiment: dict,
    price_data:    dict,
    news_data:     dict,
    tech_data:     dict,
    sec_data:      dict,
    earnings_data: dict = None,
    insider_data:  dict = None,
) -> dict:
    """
    Generate investment tactics for a single ticker using Claude Sonnet.
    Only called for medium/high conviction tickers.
    """
    lines = [
        f"TICKER: {ticker} ({company})",
        f"SENTIMENT: {sentiment.get('sentiment','').upper()} | "
        f"Conviction: {sentiment.get('conviction','').upper()} | "
        f"Reason: {sentiment.get('reasoning','')}",
    ]

    if price_data and "error" not in price_data:
        lines.append(
            f"PRICE: ${price_data.get('current_price','N/A')} | "
            f"Change: {price_data.get('change_pct','N/A')}% | "
            f"Industry: {price_data.get('industry','N/A')}"
        )

    if tech_data and "error" not in tech_data and "skipped" not in tech_data:
        cur   = price_data.get("current_price", 0)
        ma200 = tech_data.get("moving_averages", {}).get("ma_200", 0)
        lines.append(
            f"TECHNICALS: {tech_data.get('overall_signal','N/A')} | "
            f"RSI: {tech_data.get('rsi',{}).get('value','N/A')} | "
            f"MACD: {tech_data.get('macd',{}).get('crossover','N/A')} | "
            f"vs MA200: {'above' if cur > ma200 else 'below'}"
        )

    if news_data:
        ns = news_data.get("news_sentiment", {})
        headlines = [a.get("title", "") for a in news_data.get("articles", [])[:3]]
        lines.append(
            f"NEWS: {ns.get('sentiment','N/A')} "
            f"(bull={ns.get('bull_score',0)}, bear={ns.get('bear_score',0)}) | "
            f"Headlines: {headlines}"
        )

    if sec_data and "error" not in sec_data and "skipped" not in sec_data:
        lines.append(
            f"SEC: 10-K={sec_data.get('latest_10k',{}).get('date','N/A')} | "
            f"10-Q={sec_data.get('latest_10q',{}).get('date','N/A')}"
        )

    if earnings_data and "error" not in earnings_data:
        lines.append(
            f"EARNINGS: {earnings_data.get('date','N/A')} | "
            f"Urgency: {earnings_data.get('urgency','N/A')} | "
            f"EPS est: {earnings_data.get('eps_estimate','N/A')}"
        )

    if insider_data and "error" not in insider_data:
        lines.append(f"INSIDER: {insider_data.get('signal','N/A')}")

    try:
        msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=(
                "You are a professional investment analyst. "
                "Produce precise, actionable analysis. "
                "Return only valid JSON, no markdown fences."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Generate a tactical investment plan for {ticker}.\n\n"
                    f"CONTEXT:\n{chr(10).join(lines)}\n\n"
                    "Return JSON with these exact keys:\n"
                    "- bull_cases: list of 2-3 bullish arguments\n"
                    "- bear_cases: list of 2-3 bearish risks\n"
                    "- entry_zone: price range to enter (e.g. \"$820-840\")\n"
                    "- stop_loss: stop loss level (e.g. \"$780\")\n"
                    "- targets: list of 1-2 price targets\n"
                    "- tactics: list of 2-3 specific action steps\n"
                    "- time_horizon: \"short-term\" | \"medium-term\" | \"long-term\"\n"
                    "- key_risks: list of 1-2 key risks to monitor\n"
                    "- themes: list of 1-2 macro themes this fits into"
                ),
            }],
        )
        return parse_llm_json(msg.content[0].text)
    except Exception as e:
        print(f"  ⚠️  Tactic generation failed for {ticker}: {e}")
        return _EMPTY.copy()
