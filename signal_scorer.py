import os
import json
import glob
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}
ETF_TICKERS = {
    "XEQT", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU"
}


def score_ticker(ticker, reports):
    """
    Score a ticker from 0–10 based on signal agreement across:
    1. Video/article sentiment      (0–2 pts)
    2. News sentiment               (0–1 pt)
    3. Technical signal             (0–2 pts)
    4. RSI zone                     (0–1 pt)
    5. MACD crossover               (0–1 pt)
    6. Conviction level             (0–1 pt)
    7. Confidence score             (0–1 pt)
    8. Insider trading signal       (0–1 pt)
    """
    ticker_upper = ticker.upper()
    is_commodity = ticker_upper in COMMODITY_KEYWORDS
    is_etf       = ticker_upper in ETF_TICKERS

    scores     = []
    components = {}

    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            if t.get("ticker", "").upper() != ticker_upper:
                continue

            score = 0.0
            breakdown = {}

            # 1 — Sentiment (0–2)
            sentiment  = t.get("sentiment", "neutral").lower()
            conviction = t.get("conviction", "medium").lower()
            if sentiment == "bullish":
                s = 2.0 if conviction == "high" else 1.5 if conviction == "medium" else 1.0
            elif sentiment == "bearish":
                s = 0.0 if conviction == "high" else 0.5 if conviction == "medium" else 1.0
            else:
                s = 1.0
            score             += s
            breakdown["sentiment"] = round(s, 2)

            # 2 — News sentiment (0–1)
            news      = r.get("news_data",  {}).get(ticker, {})
            news_sent = news.get("news_sentiment", {}).get("sentiment", "neutral").lower()
            if   news_sent == "bullish": ns = 1.0
            elif news_sent == "bearish": ns = 0.0
            else:                        ns = 0.5
            score              += ns
            breakdown["news"]   = ns

            # 3 — Technical signal (0–2)
            tech    = r.get("tech_data", {}).get(ticker, {})
            tech_ok = tech and "error" not in tech and "skipped" not in tech
            if tech_ok:
                sig = tech.get("overall_signal", "").lower()
                if   "strong buy"  in sig: ts = 2.0
                elif "buy"         in sig: ts = 1.5
                elif "strong sell" in sig: ts = 0.0
                elif "sell"        in sig: ts = 0.5
                else:                      ts = 1.0
            elif is_commodity or is_etf:
                ts = 1.0
            else:
                ts = 1.0
            score              += ts
            breakdown["tech"]   = ts

            # 4 — RSI zone (0–1)
            if tech_ok:
                rsi_val = tech.get("rsi", {}).get("value")
                if rsi_val is not None:
                    try:
                        rsi_num = float(rsi_val)
                        if   rsi_num < 30: rs = 1.0   # oversold — bullish
                        elif rsi_num > 70: rs = 0.0   # overbought — bearish
                        else:              rs = 0.5
                    except Exception:
                        rs = 0.5
                else:
                    rs = 0.5
            else:
                rs = 0.5
            score            += rs
            breakdown["rsi"]  = rs

            # 5 — MACD crossover (0–1)
            if tech_ok:
                crossover = tech.get("macd", {}).get("crossover", "neutral").lower()
                mc = 1.0 if crossover == "bullish" else 0.0 if crossover == "bearish" else 0.5
            else:
                mc = 0.5
            score             += mc
            breakdown["macd"]  = mc

            # 6 — Conviction (0–1)
            cv = 1.0 if conviction == "high" else 0.5 if conviction == "medium" else 0.25
            score                 += cv
            breakdown["conviction"] = cv

            # 7 — Confidence score (0–1)
            confidence = r.get("analysis", {}).get("confidence_score", 0)
            cs = round(min(confidence, 1.0), 2)
            score                   += cs
            breakdown["confidence"]  = cs

            # 8 — Insider trading (0–1) — stocks only
            if not is_commodity and not is_etf:
                insider = r.get("market_context", {}).get("insider_trading", {}).get(ticker, {})
                signal  = insider.get("signal", "").lower()
                if   "buying" in signal: ins = 1.0
                elif "selling" in signal: ins = 0.0
                else:                     ins = 0.5
            else:
                ins = 0.5
            score               += ins
            breakdown["insider"] = ins

            scores.append({
                "total_score": round(score, 2),
                "breakdown":   breakdown,
                "source":      r.get("video", {}).get("channel", "N/A"),
                "date":        r.get("analyzed_at", "")[:10]
            })

    if not scores:
        return {
            "ticker":        ticker,
            "total_score":   0.0,
            "signal_label":  "NO DATA",
            "breakdown":     {},
            "scores_count":  0,
            "avg_score":     0.0
        }

    avg_score = round(sum(s["total_score"] for s in scores) / len(scores), 2)

    if   avg_score >= 8.0: label = "STRONG BUY"
    elif avg_score >= 6.5: label = "BUY"
    elif avg_score >= 5.5: label = "WEAK BUY"
    elif avg_score >= 4.5: label = "NEUTRAL"
    elif avg_score >= 3.0: label = "WEAK SELL"
    elif avg_score >= 1.5: label = "SELL"
    else:                  label = "STRONG SELL"

    latest      = max(scores, key=lambda x: x.get("date", ""))
    avg_breakdown = {}
    for key in latest["breakdown"]:
        avg_breakdown[key] = round(
            sum(s["breakdown"].get(key, 0) for s in scores) / len(scores), 2
        )

    return {
        "ticker":       ticker,
        "avg_score":    avg_score,
        "total_score":  avg_score,
        "signal_label": label,
        "breakdown":    avg_breakdown,
        "scores_count": len(scores),
        "scores":       scores
    }


def score_all_tickers(reports=None):
    if reports is None:
        reports = []
        for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(file, "r") as f:
                    reports.append(json.load(f))
            except Exception:
                continue

    tickers = set()
    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            tk = t.get("ticker")
            if tk:
                tickers.add(tk)

    results = {}
    for ticker in tickers:
        results[ticker] = score_ticker(ticker, reports)

    return dict(sorted(results.items(), key=lambda x: x[1]["avg_score"], reverse=True))


def print_scores(reports=None):
    scores = score_all_tickers(reports)
    if not scores:
        print("No ticker scores available.")
        return

    print("\n" + "=" * 60)
    print("🔔 SIGNAL STRENGTH SCORES")
    print("=" * 60)
    for ticker, data in scores.items():
        score = data["avg_score"]
        label = data["signal_label"]
        bar   = "█" * int(score)
        print(f"  {ticker:<10} {score:>4.1f}/10  {bar:<10}  {label}")
        bd = data.get("breakdown", {})
        print(f"             Sentiment:{bd.get('sentiment',0):.1f} News:{bd.get('news',0):.1f} Tech:{bd.get('tech',0):.1f} RSI:{bd.get('rsi',0):.1f} MACD:{bd.get('macd',0):.1f} Conviction:{bd.get('conviction',0):.1f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    print_scores()
