import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv


load_dotenv()


BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


def load_all_reports():
    reports = []
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                reports.append(json.load(f))
        except Exception:
            continue
    return reports


def detect_contradictions(reports=None, days=7, min_signals=2):
    """
    Detect tickers where bullish and bearish signals conflict.
    Returns dict of ticker → contradiction data.
    """
    if reports is None:
        reports = load_all_reports()

    cutoff      = datetime.now() - timedelta(days=days)
    ticker_sigs = defaultdict(lambda: {"bullish": [], "bearish": [], "neutral": []})

    for r in reports:
        ts = r.get("analyzed_at", "")
        try:
            if len(ts) >= 15:
                report_time = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
                if report_time < cutoff:
                    continue
        except Exception:
            pass

        for t in r.get("analysis", {}).get("tickers", []):
            ticker = (t.get("ticker") or "").upper().strip()
            if not ticker:
                continue

            # ✅ Safe sentiment normalization
            raw_sentiment = (t.get("sentiment") or "neutral").lower().strip()
            if raw_sentiment not in ("bullish", "bearish", "neutral"):
                raw_sentiment = "neutral"

            conviction = (t.get("conviction") or "medium").lower().strip()
            if conviction not in ("high", "medium", "low"):
                conviction = "medium"

            confidence = r.get("analysis", {}).get("confidence_score", 0) or 0
            source     = r.get("video", {}).get("channel", "N/A") or "N/A"
            date       = ts[:10] if len(ts) >= 10 else "N/A"

            ticker_sigs[ticker][raw_sentiment].append({
                "conviction": conviction,
                "confidence": confidence,
                "source":     source,
                "date":       date,
                "context":    (t.get("context") or "")[:100]
            })

    contradictions = {}
    for ticker, sigs in ticker_sigs.items():
        bull_count = len(sigs["bullish"])
        bear_count = len(sigs["bearish"])
        total      = bull_count + bear_count

        if total < min_signals:
            continue
        if bull_count == 0 or bear_count == 0:
            continue

        # Conflict score: how evenly split is the signal?
        ratio          = min(bull_count, bear_count) / max(bull_count, bear_count)
        conflict_score = round(ratio * 10, 1)  # 0 = no conflict, 10 = perfectly split

        if   conflict_score >= 7: level = "HIGH"
        elif conflict_score >= 4: level = "MEDIUM"
        else:                     level = "LOW"

        # Weighted signal (conviction counts double)
        bull_weight = sum(
            2.0 if s["conviction"] == "high" else 1.0
            for s in sigs["bullish"]
        )
        bear_weight = sum(
            2.0 if s["conviction"] == "high" else 1.0
            for s in sigs["bearish"]
        )

        if bull_weight > bear_weight * 1.5:
            dominant       = "BULLISH"
            recommendation = "Lean bullish but position size small — conflicting signals"
        elif bear_weight > bull_weight * 1.5:
            dominant       = "BEARISH"
            recommendation = "Lean bearish but position size small — conflicting signals"
        else:
            dominant       = "NEUTRAL"
            recommendation = "Avoid — signals too conflicted, wait for clarity"

        contradictions[ticker] = {
            "ticker":           ticker,
            "bullish":          bull_count,
            "bearish":          bear_count,
            "neutral":          len(sigs["neutral"]),
            "total":            total,
            "conflict_score":   conflict_score,
            "conflict_level":   level,
            "dominant":         dominant,
            "recommendation":   recommendation,
            "bull_weight":      round(bull_weight, 1),
            "bear_weight":      round(bear_weight, 1),
            "bullish_sources":  [s["source"] for s in sigs["bullish"]],
            "bearish_sources":  [s["source"] for s in sigs["bearish"]],
            "bullish_contexts": [s["context"] for s in sigs["bullish"][:2]],
            "bearish_contexts": [s["context"] for s in sigs["bearish"][:2]],
        }

    return dict(sorted(contradictions.items(), key=lambda x: x[1]["conflict_score"], reverse=True))


def print_contradictions(days=7):
    results = detect_contradictions(days=days)
    if not results:
        print(f"✅ No conflicting signals in last {days} days.")
        return

    print("\n" + "=" * 70)
    print(f"⚠️  CONFLICTING SIGNALS — Last {days} Days")
    print("=" * 70)
    for ticker, data in results.items():
        print(f"\n  🔄 {ticker} — Conflict Level: {data['conflict_level']} ({data['conflict_score']}/10)")
        print(f"     🟢 Bullish: {data['bullish']} | 🔴 Bearish: {data['bearish']} | Total: {data['total']}")
        print(f"     Dominant: {data['dominant']}")
        print(f"     💡 {data['recommendation']}")
        if data["bullish_contexts"]:
            print(f"     🟢 Bull: {data['bullish_contexts'][0][:70]}")
        if data["bearish_contexts"]:
            print(f"     🔴 Bear: {data['bearish_contexts'][0][:70]}")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    print_contradictions()
