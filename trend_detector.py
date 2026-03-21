import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


# ── Report loader ─────────────────────────────────────────────────────────────

def _load_reports_from_db():
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            os.environ["DATABASE_URL"],
            connect_args={"sslmode": "require"},
            pool_pre_ping=True
        )
        report_map = {}
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT r.id, r.analyzed_at, r.channel,
                       s.ticker, s.sentiment, s.context_text
                FROM reports r
                LEFT JOIN signals s ON s.report_id = r.id
                ORDER BY r.analyzed_at DESC
                LIMIT 2000
            """)).fetchall()

        for row in rows:
            rid = row[0]
            if rid not in report_map:
                report_map[rid] = {
                    "analyzed_at": row[1].strftime("%Y%m%d_%H%M%S") if row[1] else "",
                    "video":    {"channel": row[2] or "N/A"},
                    "analysis": {"tickers": []}
                }
            if row[3]:
                report_map[rid]["analysis"]["tickers"].append({
                    "ticker":    row[3],
                    "sentiment": row[4] or "neutral",
                    "context":   row[5] or ""
                })

        reports = list(report_map.values())
        print(f"  🗄️  Loaded {len(reports)} reports from DB (trend detector)")
        return reports

    except Exception as e:
        print(f"  ⚠️  DB unavailable ({e}) — falling back to JSON")
        return None


def _load_reports():
    if os.environ.get("DATABASE_URL"):
        result = _load_reports_from_db()
        if result is not None:
            return result
    # JSON fallback
    reports = []
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                reports.append(json.load(f))
        except Exception:
            continue
    return reports


# ── Core functions ────────────────────────────────────────────────────────────

def detect_trending_tickers(reports=None, window_recent=7, window_baseline=21, min_recent=2):
    """
    Detect tickers gaining sudden attention.
    Compares mention count in last `window_recent` days vs prior `window_baseline` days.
    Returns list of trending tickers sorted by breakout score.
    """
    if reports is None:
        reports = _load_reports()

    now             = datetime.now()
    recent_cutoff   = now - timedelta(days=window_recent)
    baseline_cutoff = now - timedelta(days=window_baseline)

    recent_counts   = defaultdict(lambda: {"count": 0, "bull": 0, "bear": 0,
                                            "sources": set(), "contexts": []})
    baseline_counts = defaultdict(int)

    for r in reports:
        ts = r.get("analyzed_at", "")
        try:
            if len(ts) >= 15:
                rt = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
            else:
                continue
        except Exception:
            continue

        in_recent   = rt >= recent_cutoff
        in_baseline = baseline_cutoff <= rt < recent_cutoff
        source      = (r.get("video", {}).get("channel") or "N/A")

        for t in r.get("analysis", {}).get("tickers", []):
            ticker    = (t.get("ticker") or "").upper().strip()
            sentiment = (t.get("sentiment") or "neutral").lower().strip()
            if not ticker:
                continue
            if sentiment not in ("bullish", "bearish", "neutral"):
                sentiment = "neutral"

            if in_recent:
                recent_counts[ticker]["count"]  += 1
                recent_counts[ticker]["sources"].add(source)
                if sentiment == "bullish": recent_counts[ticker]["bull"] += 1
                if sentiment == "bearish": recent_counts[ticker]["bear"] += 1
                ctx = (t.get("context") or "")[:100]
                if ctx:
                    recent_counts[ticker]["contexts"].append(ctx)

            if in_baseline:
                baseline_counts[ticker] += 1

    results = []
    for ticker, rc in recent_counts.items():
        r_count = rc["count"]
        if r_count < min_recent:
            continue

        b_count = baseline_counts.get(ticker, 0)

        recent_per_day   = r_count / window_recent
        baseline_per_day = b_count / (window_baseline - window_recent) if b_count > 0 else 0.01

        breakout_score = round(recent_per_day / baseline_per_day, 2)
        is_new         = b_count == 0

        total    = rc["bull"] + rc["bear"]
        bull_pct = round((rc["bull"] / total * 100) if total > 0 else 50, 1)
        bias     = "🟢 Bullish" if bull_pct > 60 else "🔴 Bearish" if bull_pct < 40 else "🟡 Mixed"

        results.append({
            "ticker":         ticker,
            "recent_count":   r_count,
            "baseline_count": b_count,
            "breakout_score": breakout_score,
            "is_new":         is_new,
            "bull_pct":       bull_pct,
            "bias":           bias,
            "sources":        sorted(rc["sources"]),
            "source_count":   len(rc["sources"]),
            "contexts":       rc["contexts"][:2],
            "alert":          "🆕 NEW" if is_new else (
                               "🔥 HOT" if breakout_score >= 5 else
                               "📈 RISING" if breakout_score >= 2 else
                               "👀 WATCH"
                              )
        })

    return sorted(results, key=lambda x: x["breakout_score"], reverse=True)


def get_trend_summary(reports=None):
    """Quick summary — top 5 trending tickers."""
    trends = detect_trending_tickers(reports=reports)
    return trends[:5]


def print_trends():
    results = detect_trending_tickers()
    if not results:
        print("No trending tickers detected.")
        return

    print("\n" + "=" * 70)
    print("📈 TRENDING TICKERS — Breakout Attention Detector")
    print("=" * 70)
    for t in results:
        print(f"\n  {t['alert']} {t['ticker']} — Breakout: {t['breakout_score']}x")
        print(f"     Recent: {t['recent_count']} mentions | Baseline: {t['baseline_count']}")
        print(f"     Bias: {t['bias']} ({t['bull_pct']}% bull) | Sources: {t['source_count']}")
        if t["contexts"]:
            print(f"     Context: {t['contexts'][0][:70]}")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    print_trends()
