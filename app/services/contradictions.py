import os, json, glob
from datetime import datetime, timedelta
from config import REPORTS_DIR


def detect_contradictions(reports: list = None, days: int = 14) -> list:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue

    cutoff  = datetime.now() - timedelta(days=days)
    signals = {}

    for r in reports:
        try:
            ts = datetime.strptime(r.get("analyzed_at", "")[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        if ts < cutoff:
            continue
        for t in r.get("analysis", {}).get("tickers", []):
            tk   = (t.get("ticker") or "").upper()
            sent = (t.get("sentiment") or "neutral").lower()
            conv = (t.get("conviction") or "medium").lower()
            if tk not in signals:
                signals[tk] = []
            weight = 2 if conv == "high" else 1
            signals[tk].append({"sentiment": sent, "weight": weight,
                                 "source": r.get("video", {}).get("channel", "N/A")})

    results = []
    for tk, sigs in signals.items():
        bull_w = sum(s["weight"] for s in sigs if s["sentiment"] == "bullish")
        bear_w = sum(s["weight"] for s in sigs if s["sentiment"] == "bearish")
        if bull_w == 0 or bear_w == 0:
            continue
        total  = bull_w + bear_w
        ratio  = min(bull_w, bear_w) / max(bull_w, bear_w)
        score  = round(ratio * 10, 1)
        if bull_w > bear_w:
            lean = "LEAN BULLISH"
        elif bear_w > bull_w:
            lean = "LEAN BEARISH"
        else:
            lean = "AVOID — perfectly split"
        results.append({
            "ticker":         tk,
            "bull_weight":    bull_w,
            "bear_weight":    bear_w,
            "conflict_score": score,
            "recommendation": lean,
        })

    return sorted(results, key=lambda x: x["conflict_score"], reverse=True)
