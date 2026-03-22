"""
app/services/pipeline.py — Multi-agent processing orchestrator.

Flow per article/video:
  1. Extract tickers              — Claude Haiku (ticker_extractor)
  2. Fetch market data            — parallel (prices, news, technicals, SEC, memory)
  3. Per-ticker sentiment         — Claude Haiku x N tickers in parallel (sentiment_agent)
  4. Market context               — parallel (Fear & Greed, earnings, insider)
  5. Per-ticker tactics           — Claude Sonnet x M tickers in parallel (tactic_agent)
                                    (only medium + high conviction tickers)
  6. Aggregate into report format — backwards-compatible with dashboard
  7. Log predictions + save report
"""

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from app.agents.ticker_extractor import extract_tickers
from app.agents.sentiment_agent  import analyze as sentiment_analyze
from app.agents.tactic_agent     import generate as tactic_generate
from app.collectors.prices       import get_price, get_sec_data
from app.collectors.news         import get_news
from app.collectors.technicals   import get_technicals
from app.services.context        import get_market_context
from app.services.tracker        import log_prediction, evaluate_predictions, get_accuracy_stats, get_model_memory
from app.db.writer               import save_report
from config import COMMODITY_KEYWORDS, SKIP_TECHNICALS, ETF_TICKERS, MIN_CONFIDENCE


# ── Helpers ──────────────────────────────────────────────────────────────────

def _conviction_score(conviction: str) -> float:
    return {"high": 1.0, "medium": 0.65, "low": 0.3}.get(conviction.lower(), 0.3)


def _aggregate_sentiment(sentiment_map: dict) -> str:
    """Majority vote weighted by conviction."""
    bull = bear = neutral = 0.0
    for s in sentiment_map.values():
        w = _conviction_score(s.get("conviction", "low"))
        sent = s.get("sentiment", "neutral").lower()
        if sent == "bullish":  bull    += w
        elif sent == "bearish": bear   += w
        else:                   neutral += w
    if bull > bear and bull > neutral:   return "bullish"
    if bear > bull and bear > neutral:   return "bearish"
    return "neutral"


def _compute_confidence(sentiment_map: dict) -> float:
    """Average conviction score, scaled 0–1."""
    if not sentiment_map:
        return 0.0
    scores = [_conviction_score(s.get("conviction", "low")) for s in sentiment_map.values()]
    return round(sum(scores) / len(scores), 2)


def _collect_themes(tactic_map: dict) -> list:
    return list(dict.fromkeys(
        theme for t in tactic_map.values() for theme in t.get("themes", [])
    ))


def _collect_list(tactic_map: dict, key: str, limit: int = 6) -> list:
    return list(dict.fromkeys(
        item for t in tactic_map.values() for item in t.get(key, [])
    ))[:limit]


# ── Main entry point ─────────────────────────────────────────────────────────

def process(content: dict) -> dict | None:
    """
    Process one content item (YouTube video or news article).

    content = {
        "id":           str,
        "title":        str,
        "body":         str,
        "source":       str,
        "url":          str,
        "published_at": str,
        "type":         "youtube" | "rss" | "newsapi"
    }
    """
    print(f"\n{'─'*60}")
    print(f"⚙️  Processing: {content['title'][:70]}")
    print(f"   Source: {content['source']} | Type: {content['type']}")

    # Evaluate old predictions at start of each run
    evaluate_predictions()
    stats = get_accuracy_stats()
    if stats:
        print(f"   🧠 Model accuracy: {stats['accuracy']}% ({stats['correct']}/{stats['total']})")

    body = content.get("body", "")
    if len(body) < 100:
        print("   ⚠️  Content too short — skipping")
        return None

    # ── Step 1: Extract tickers ─────────────────────────────────────────────
    print("   🔍 Step 1: Extracting tickers...")
    tickers_raw = extract_tickers(body)
    if not tickers_raw:
        print("   ⚠️  No tickers found — skipping")
        return None
    print(f"   ✅ Found: {[t['ticker'] for t in tickers_raw]}")

    # ── Step 2: Fetch market data in parallel ───────────────────────────────
    print(f"   📡 Step 2: Fetching market data for {len(tickers_raw)} tickers in parallel...")
    price_map, news_map, tech_map, sec_map, memory_map = {}, {}, {}, {}, {}

    with ThreadPoolExecutor(max_workers=20) as pool:
        price_f   = {t["ticker"]: pool.submit(get_price,        t["ticker"]) for t in tickers_raw}
        news_f    = {t["ticker"]: pool.submit(get_news,         t["ticker"], t.get("company", "")) for t in tickers_raw}
        sec_f     = {t["ticker"]: pool.submit(get_sec_data,     t["ticker"]) for t in tickers_raw}
        memory_f  = {t["ticker"]: pool.submit(get_model_memory, t["ticker"]) for t in tickers_raw}
        tech_f    = {}
        for t in tickers_raw:
            tk = t["ticker"]
            if tk.upper() in SKIP_TECHNICALS:
                tech_map[tk] = {"skipped": "Commodity — no technical indicators"}
            else:
                tech_f[tk] = pool.submit(get_technicals, tk)

        for tk, f in price_f.items():   price_map[tk]  = f.result()
        for tk, f in news_f.items():    news_map[tk]   = f.result()
        for tk, f in sec_f.items():     sec_map[tk]    = f.result()
        for tk, f in memory_f.items():  memory_map[tk] = f.result()
        for tk, f in tech_f.items():    tech_map[tk]   = f.result()

    print("   ✅ Market data fetched")

    # ── Step 3: Per-ticker sentiment (Haiku, parallel) ──────────────────────
    print(f"   🤖 Step 3: Sentiment analysis for {len(tickers_raw)} tickers in parallel...")
    sentiment_map = {}

    with ThreadPoolExecutor(max_workers=len(tickers_raw) or 1) as pool:
        sent_futures = {
            t["ticker"]: pool.submit(
                sentiment_analyze,
                t["ticker"],
                t.get("company", ""),
                t.get("context", ""),
                price_map.get(t["ticker"], {}),
                news_map.get(t["ticker"], {}),
            )
            for t in tickers_raw
        }
        for tk, f in sent_futures.items():
            sentiment_map[tk] = f.result()
            s = sentiment_map[tk]
            print(f"      {tk}: {s['sentiment'].upper()} ({s['conviction']}) — {s['reasoning'][:60]}")

    # ── Step 4: Market context in parallel ──────────────────────────────────
    stock_tickers = [
        t["ticker"] for t in tickers_raw
        if t["ticker"].upper() not in COMMODITY_KEYWORDS
        and t["ticker"].upper() not in ETF_TICKERS
    ]
    print("   🌍 Step 4: Fetching market context...")
    market_ctx = get_market_context(stock_tickers) if stock_tickers else {}

    fg = market_ctx.get("fear_and_greed", {})
    if "score" in fg:
        print(f"      Fear & Greed: {fg['score']} — {fg.get('signal','N/A')[:40]}")

    # ── Step 5: Per-ticker tactics (Sonnet, only medium/high conviction) ────
    high_conv_tickers = [
        t for t in tickers_raw
        if sentiment_map.get(t["ticker"], {}).get("conviction") in ("medium", "high")
    ]
    tactic_map = {}

    if high_conv_tickers:
        print(f"   🎯 Step 5: Generating tactics for {len(high_conv_tickers)} high-conviction tickers...")
        earnings_cal = market_ctx.get("earnings_calendar", {})
        insider_data = market_ctx.get("insider_trading", {})

        with ThreadPoolExecutor(max_workers=len(high_conv_tickers)) as pool:
            tactic_futures = {
                t["ticker"]: pool.submit(
                    tactic_generate,
                    t["ticker"],
                    t.get("company", ""),
                    sentiment_map[t["ticker"]],
                    price_map.get(t["ticker"], {}),
                    news_map.get(t["ticker"], {}),
                    tech_map.get(t["ticker"], {}),
                    sec_map.get(t["ticker"], {}),
                    earnings_cal.get(t["ticker"], {}),
                    insider_data.get(t["ticker"], {}),
                )
                for t in high_conv_tickers
            }
            for tk, f in tactic_futures.items():
                tactic_map[tk] = f.result()
                print(f"      {tk}: {len(tactic_map[tk].get('tactics',[]))} tactics generated")
    else:
        print("   ⏭️  Step 5: No high-conviction tickers — skipping tactic generation")

    # ── Step 6: Build report ─────────────────────────────────────────────────
    ticker_lookup = {t["ticker"]: t for t in tickers_raw}
    tickers_out = []
    for tk, sent in sentiment_map.items():
        raw = ticker_lookup.get(tk, {})
        tac = tactic_map.get(tk, {})
        tickers_out.append({
            "ticker":       tk,
            "company":      raw.get("company", ""),
            "sentiment":    sent["sentiment"],
            "conviction":   sent["conviction"],
            "context":      raw.get("context", ""),
            "reasoning":    sent.get("reasoning", ""),
            "bull_cases":   tac.get("bull_cases",  []),
            "bear_cases":   tac.get("bear_cases",  []),
            "tactics":      tac.get("tactics",     []),
            "entry_zone":   tac.get("entry_zone",  ""),
            "stop_loss":    tac.get("stop_loss",   ""),
            "targets":      tac.get("targets",     []),
            "time_horizon": tac.get("time_horizon",""),
            "key_risks":    tac.get("key_risks",   []),
        })

    overall_sentiment = _aggregate_sentiment(sentiment_map)
    confidence        = _compute_confidence(sentiment_map)

    analysis = {
        "tickers":                tickers_out,
        "key_themes":             _collect_themes(tactic_map),
        "bull_cases":             _collect_list(tactic_map, "bull_cases"),
        "bear_cases":             _collect_list(tactic_map, "bear_cases"),
        "investment_tactics":     _collect_list(tactic_map, "tactics"),
        "overall_market_sentiment": overall_sentiment,
        "confidence_score":       confidence,
    }

    print(f"   📊 Overall: {overall_sentiment.upper()} | Confidence: {confidence:.0%}")

    # ── Step 7: Log predictions ──────────────────────────────────────────────
    if confidence >= MIN_CONFIDENCE:
        print("   📝 Step 7: Logging predictions...")
        for t in tickers_out:
            tk    = t["ticker"]
            price = price_map.get(tk, {}).get("current_price", 0)
            log_prediction(
                ticker=tk,
                sentiment=t["sentiment"],
                price_at_prediction=price,
                confidence=confidence,
                video_id=content["id"],
                video_title=f"[{content['source']}] {content['title'][:60]}",
            )
    else:
        print(f"   ⏭️  Low confidence ({confidence:.0%}) — skipping prediction logging")

    # ── Build and save report ────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "analyzed_at": timestamp,
        "video": {
            "video_id":     content["id"][:50].replace("/", "_").replace(":", "_"),
            "title":        f"[{content['source']}] {content['title']}",
            "channel":      content["source"],
            "published_at": content.get("published_at", ""),
            "url":          content.get("url", ""),
            "type":         content.get("type", "unknown"),
        },
        "analysis":       analysis,
        "price_data":     price_map,
        "sec_data":       sec_map,
        "news_data":      news_map,
        "tech_data":      tech_map,
        "market_context": market_ctx,
    }
    save_report(report)

    tickers_found = [t["ticker"] for t in tickers_out]
    print(f"   ✅ Done — {len(tickers_found)} tickers: {tickers_found}")
    return report
