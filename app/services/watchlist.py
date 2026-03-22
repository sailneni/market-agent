import os, json, glob
from datetime import datetime, timedelta
from config import BASE_DIR, REPORTS_DIR

WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")


def get_top_tickers(reports: list = None, min_mentions: int = 2, top_n: int = 20) -> list:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue

    cutoff  = datetime.now() - timedelta(days=30)
    scores  = {}

    for r in reports:
        try:
            ts = datetime.strptime(r.get("analyzed_at", "")[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        recency = max(0, 1 - (datetime.now() - ts).days / 30)
        for t in r.get("analysis", {}).get("tickers", []):
            tk   = (t.get("ticker") or "").upper()
            sent = (t.get("sentiment") or "neutral").lower()
            conv = (t.get("conviction") or "medium").lower()
            if not tk:
                continue
            if tk not in scores:
                scores[tk] = {"mentions": 0, "bull": 0, "bear": 0, "sources": set(), "score": 0.0}
            scores[tk]["mentions"] += 1
            scores[tk]["sources"].add(r.get("video", {}).get("channel", ""))
            if sent == "bullish": scores[tk]["bull"] += 1
            elif sent == "bearish": scores[tk]["bear"] += 1
            bonus = 1.5 if conv == "high" else 1.0 if conv == "medium" else 0.5
            scores[tk]["score"] += bonus * recency

    result = []
    for tk, d in scores.items():
        if d["mentions"] < min_mentions:
            continue
        result.append({
            "ticker":        tk,
            "mentions":      d["mentions"],
            "bull":          d["bull"],
            "bear":          d["bear"],
            "sources":       len(d["sources"]),
            "score":         round(d["score"], 2),
        })

    return sorted(result, key=lambda x: x["score"], reverse=True)[:top_n]


def save_watchlist(tickers: list):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(tickers, f, indent=2)
