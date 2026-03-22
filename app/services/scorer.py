import os, json, glob
from config import REPORTS_DIR, COMMODITY_KEYWORDS, ETF_TICKERS


def score_ticker(ticker: str, reports: list) -> dict:
    ticker_upper = ticker.upper()
    is_commodity = ticker_upper in COMMODITY_KEYWORDS
    is_etf       = ticker_upper in ETF_TICKERS
    scores       = []

    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            if t.get("ticker", "").upper() != ticker_upper:
                continue
            score      = 0.0
            sentiment  = t.get("sentiment", "neutral").lower()
            conviction = t.get("conviction", "medium").lower()

            # Sentiment (0-2)
            if sentiment == "bullish":
                s = 2.0 if conviction == "high" else 1.5 if conviction == "medium" else 1.0
            elif sentiment == "bearish":
                s = 0.0 if conviction == "high" else 0.5 if conviction == "medium" else 1.0
            else:
                s = 1.0
            score += s

            # News (0-1)
            news_sent = r.get("news_data", {}).get(ticker, {}).get("news_sentiment", {}).get("sentiment", "neutral").lower()
            score    += 1.0 if news_sent == "bullish" else 0.0 if news_sent == "bearish" else 0.5

            # Technical (0-2)
            tech    = r.get("tech_data", {}).get(ticker, {})
            tech_ok = tech and "error" not in tech and "skipped" not in tech
            if tech_ok:
                sig = tech.get("overall_signal", "").lower()
                ts  = 2.0 if "strong buy" in sig else 1.5 if "buy" in sig else 0.0 if "strong sell" in sig else 0.5 if "sell" in sig else 1.0
            else:
                ts = 1.0
            score += ts

            # RSI (0-1)
            rsi_val = tech.get("rsi", {}).get("value") if tech_ok else None
            if rsi_val is not None:
                try:    score += 1.0 if float(rsi_val) < 30 else 0.0 if float(rsi_val) > 70 else 0.5
                except: score += 0.5
            else:
                score += 0.5

            # MACD (0-1)
            crossover = tech.get("macd", {}).get("crossover", "neutral").lower() if tech_ok else "neutral"
            score    += 1.0 if crossover == "bullish" else 0.0 if crossover == "bearish" else 0.5

            # Conviction (0-1)
            score += 1.0 if conviction == "high" else 0.5 if conviction == "medium" else 0.25

            # Confidence (0-1)
            score += min(r.get("analysis", {}).get("confidence_score", 0), 1.0)

            # Insider (0-1) stocks only
            if not is_commodity and not is_etf:
                sig = r.get("market_context", {}).get("insider_trading", {}).get(ticker, {}).get("signal", "").lower()
                score += 1.0 if "buying" in sig else 0.0 if "selling" in sig else 0.5
            else:
                score += 0.5

            scores.append(round(score, 2))

    if not scores:
        return {"ticker": ticker, "avg_score": 0.0, "signal_label": "NO DATA", "scores_count": 0}

    avg = round(sum(scores) / len(scores), 2)
    label = ("STRONG BUY" if avg >= 8.0 else "BUY" if avg >= 6.5 else "WEAK BUY" if avg >= 5.5
             else "NEUTRAL" if avg >= 4.5 else "WEAK SELL" if avg >= 3.0 else "SELL" if avg >= 1.5
             else "STRONG SELL")
    return {"ticker": ticker, "avg_score": avg, "signal_label": label, "scores_count": len(scores)}


def score_all_tickers(reports: list = None) -> dict:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue
    tickers = {t.get("ticker") for r in reports for t in r.get("analysis", {}).get("tickers", []) if t.get("ticker")}
    return dict(sorted({t: score_ticker(t, reports) for t in tickers}.items(),
                       key=lambda x: x[1]["avg_score"], reverse=True))
