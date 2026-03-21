import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")

COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}
ETF_TICKERS = {
    "XEQT", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU"
}

VALID_SENTIMENTS  = {"bullish", "bearish", "neutral"}
VALID_CONVICTIONS = {"high", "medium", "low"}


def get_asset_type(ticker):
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS: return "commodity"
    if t in ETF_TICKERS:        return "etf"
    return "stock"


def load_all_reports():
    reports = []
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                reports.append(json.load(f))
        except Exception:
            continue
    return reports


def analyze_reports(reports, days=30):
    """
    Aggregate ticker stats from all reports within the last N days.
    Returns dict: ticker → stats dict.
    """
    cutoff = datetime.now() - timedelta(days=days)
    stats  = defaultdict(lambda: {
        "count":          0,
        "bullish":        0,
        "bearish":        0,
        "neutral":        0,
        "high_conviction": 0,
        "sources":        set(),
        "contexts":       [],
        "last_seen":      "",
        "asset_type":     "stock",
        "score":          0.0,
    })

    for r in reports:
        ts = r.get("analyzed_at", "")
        try:
            if len(ts) >= 15:
                report_time = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
                if report_time < cutoff:
                    continue
        except Exception:
            pass

        source = (r.get("video", {}).get("channel") or "N/A")
        date   = ts[:10] if len(ts) >= 10 else ""

        for t in r.get("analysis", {}).get("tickers", []):
            ticker = (t.get("ticker") or "").upper().strip()
            if not ticker:
                continue

            # ✅ Safe sentiment normalization
            raw_sentiment = (t.get("sentiment") or "neutral").lower().strip()
            if raw_sentiment not in VALID_SENTIMENTS:
                raw_sentiment = "neutral"

            # ✅ Safe conviction normalization
            raw_conviction = (t.get("conviction") or "medium").lower().strip()
            if raw_conviction not in VALID_CONVICTIONS:
                raw_conviction = "medium"

            s = stats[ticker]
            s["count"]      += 1
            s[raw_sentiment] += 1          # ✅ now always a valid key
            s["sources"].add(source)
            s["asset_type"] = get_asset_type(ticker)

            if raw_conviction == "high":
                s["high_conviction"] += 1

            context = (t.get("context") or "")[:100]
            if context:
                s["contexts"].append(context)

            if date and date > s["last_seen"]:
                s["last_seen"] = date

    return stats


def score_ticker_stats(s):
    """
    Score a ticker 0–10 based on mentions, conviction, recency, source diversity.
    """
    count       = s["count"]
    bull        = s["bullish"]
    bear        = s["bearish"]
    hi_conv     = s["high_conviction"]
    sources     = len(s["sources"])
    last_seen   = s["last_seen"]

    mention_score    = min(count / 5.0, 2.0)
    conviction_score = min(hi_conv / 2.0, 2.0)
    source_score     = min(sources / 3.0, 2.0)

    total = bull + bear
    sentiment_score = (bull / total * 2.0) if total > 0 else 1.0

    recency_score = 0.0
    if last_seen:
        try:
            days_ago = (datetime.now() - datetime.strptime(last_seen, "%Y-%m-%d")).days
            recency_score = max(0.0, 2.0 - days_ago * 0.1)
        except Exception:
            pass

    return round(mention_score + conviction_score + source_score + sentiment_score + recency_score, 2)


def get_top_tickers(reports=None, top_n=30, min_mentions=2, days=30):
    """
    Return top N tickers ranked by score.
    Each entry is a dict with full stats for display.
    """
    if reports is None:
        reports = load_all_reports()

    stats = analyze_reports(reports, days=days)

    results = []
    for ticker, s in stats.items():
        if s["count"] < min_mentions:
            continue

        score = score_ticker_stats(s)
        s["score"] = score

        total     = s["bullish"] + s["bearish"] + s["neutral"]
        bull_pct  = round((s["bullish"] / total * 100) if total > 0 else 0, 1)

        results.append({
            "ticker":         ticker,
            "count":          s["count"],
            "bullish":        s["bullish"],
            "bearish":        s["bearish"],
            "neutral":        s["neutral"],
            "bull_pct":       bull_pct,
            "high_conviction": s["high_conviction"],
            "source_count":   len(s["sources"]),
            "sources":        list(s["sources"]),
            "last_seen":      s["last_seen"],
            "asset_type":     s["asset_type"],
            "score":          score,
            "contexts":       s["contexts"][:3],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def save_watchlist(reports=None, top_n=30, min_mentions=2):
    """Save top tickers to watchlist.json."""
    top = get_top_tickers(reports=reports, top_n=top_n, min_mentions=min_mentions)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "ticker_count":  len(top),
        "tickers":       top
    }

    with open(WATCHLIST_FILE, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✅ Watchlist saved: {len(top)} tickers → {WATCHLIST_FILE}")
    return top


def load_watchlist():
    """Load saved watchlist from disk."""
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r") as f:
            data = json.load(f)
            return data.get("tickers", [])
    except Exception:
        return []


def print_watchlist(top_n=20):
    results = get_top_tickers(top_n=top_n)
    if not results:
        print("No tickers found yet.")
        return

    print("\n" + "=" * 70)
    print(f"🔥 AUTO WATCHLIST — Top {len(results)} Tickers")
    print("=" * 70)
    for e in results:
        bias = "🟢 Bullish" if e["bull_pct"] > 60 else "🔴 Bearish" if e["bull_pct"] < 40 else "🟡 Mixed"
        print(f"\n  {e['ticker']} ({e['asset_type'].upper()}) — Score: {e['score']}/10")
        print(f"     Mentions: {e['count']} | {bias} ({e['bull_pct']}%) | Hi-Conv: {e['high_conviction']}")
        print(f"     Sources: {e['source_count']} | Last Seen: {e['last_seen']}")
        if e["contexts"]:
            print(f"     Context: {e['contexts'][0][:70]}")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    print_watchlist()
