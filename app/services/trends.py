import os, json, glob
from datetime import datetime, timedelta
from config import REPORTS_DIR


def detect_trending_tickers(reports: list = None, recent_days: int = 7, baseline_days: int = 21) -> list:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue

    now      = datetime.now()
    recent   = now - timedelta(days=recent_days)
    baseline = now - timedelta(days=baseline_days)

    recent_counts   = {}
    baseline_counts = {}

    for r in reports:
        try:
            ts = datetime.strptime(r.get("analyzed_at", "")[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        for t in r.get("analysis", {}).get("tickers", []):
            tk = t.get("ticker")
            if not tk:
                continue
            if ts >= recent:
                recent_counts[tk] = recent_counts.get(tk, 0) + 1
            if ts >= baseline:
                baseline_counts[tk] = baseline_counts.get(tk, 0) + 1

    results = []
    for tk, rc in recent_counts.items():
        bc = baseline_counts.get(tk, 0)
        base_per_day   = bc / baseline_days if bc else 0
        recent_per_day = rc / recent_days
        breakout       = round(recent_per_day / base_per_day, 1) if base_per_day else 99.0
        if bc == 0:
            status = "NEW"
        elif breakout >= 5:
            status = "HOT"
        elif breakout >= 2:
            status = "RISING"
        elif breakout >= 1.2:
            status = "WATCH"
        else:
            continue
        results.append({
            "ticker":       tk,
            "status":       status,
            "recent_count": rc,
            "breakout":     breakout,
        })

    return sorted(results, key=lambda x: x["breakout"], reverse=True)
