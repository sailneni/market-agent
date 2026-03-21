import os
import json
import glob
import logging
import yfinance as yf
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# Suppress yfinance "possibly delisted" warnings
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

COMMODITY_MAP = {"GOLD": "GC=F", "SILVER": "SI=F", "XAU": "GC=F", "XAG": "SI=F"}


# ── DB loader ────────────────────────────────────────────────────────────────

def _load_reports_from_db():
    """Load reports from Supabase DB. Returns list of report-shaped dicts."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            os.environ["DATABASE_URL"],
            connect_args={"sslmode": "require"},
            pool_pre_ping=True
        )
        reports = []
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT r.id, r.analyzed_at, r.channel, r.title, r.confidence,
                       s.ticker, s.sentiment, s.conviction
                FROM reports r
                JOIN signals s ON s.report_id = r.id
                ORDER BY r.analyzed_at DESC
            """)).fetchall()

        # Group signals back into report-shaped dicts
        report_map = {}
        for row in rows:
            rid = row[0]
            if rid not in report_map:
                report_map[rid] = {
                    "analyzed_at": row[1].strftime("%Y%m%d_%H%M%S") if row[1] else "",
                    "video": {
                        "channel": row[2] or "N/A",
                        "title":   row[3] or ""
                    },
                    "analysis": {
                        "confidence_score": float(row[4]) if row[4] else 0,
                        "tickers": []
                    }
                }
            report_map[rid]["analysis"]["tickers"].append({
                "ticker":     row[5],
                "sentiment":  row[6],
                "conviction": row[7]
            })

        reports = list(report_map.values())
        print(f"  🗄️  Loaded {len(reports)} reports from Supabase DB")
        return reports

    except Exception as e:
        print(f"  ⚠️  DB unavailable ({e}) — falling back to JSON files")
        return None


def _load_reports_from_json():
    """Fallback: load reports from local JSON files."""
    reports = []
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                reports.append(json.load(f))
        except Exception:
            continue
    print(f"  📂 Loaded {len(reports)} reports from JSON files")
    return reports


def _load_reports():
    """Load reports from DB if available, otherwise fall back to JSON."""
    if os.environ.get("DATABASE_URL"):
        result = _load_reports_from_db()
        if result is not None:
            return result
    return _load_reports_from_json()


# ── Price fetcher ─────────────────────────────────────────────────────────────

def get_price_at(ticker, date_str, offset_days=0):
    """Fetch closing price for ticker on or near a given date."""
    try:
        sym  = COMMODITY_MAP.get(ticker.upper(), ticker)
        date = datetime.strptime(date_str[:10], "%Y-%m-%d") + timedelta(days=offset_days)

        # Skip future dates — price doesn't exist yet
        if date.date() >= datetime.now().date():
            return None

        end  = date + timedelta(days=5)
        hist = yf.Ticker(sym).history(
            start=date.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d")
        )
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[0]), 4)
    except Exception:
        return None


# ── Backtest engine ───────────────────────────────────────────────────────────

def run_backtest(reports=None, hold_days_list=None, min_confidence=0.5):
    """
    Backtest every ticker signal from reports.
    For each signal: compare price at report date vs price N days later.
    Returns list of trade results.
    """
    if reports is None:
        reports = _load_reports()
    if hold_days_list is None:
        hold_days_list = [3, 7, 14, 30]

    trades = []

    for r in reports:
        ts         = r.get("analyzed_at", "")
        confidence = r.get("analysis", {}).get("confidence_score", 0) or 0
        source     = r.get("video", {}).get("channel", "N/A") or "N/A"
        title      = r.get("video", {}).get("title", "")[:60] or ""

        if confidence < min_confidence:
            continue

        try:
            date_str = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d")
        except Exception:
            continue

        # Skip reports from today — no meaningful exit price available
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if report_date >= datetime.now().date():
                continue
        except Exception:
            continue

        for t in r.get("analysis", {}).get("tickers", []):
            ticker     = (t.get("ticker") or "").upper().strip()
            sentiment  = (t.get("sentiment") or "neutral").lower().strip()
            conviction = (t.get("conviction") or "medium").lower().strip()

            if not ticker or sentiment not in ("bullish", "bearish"):
                continue
            if conviction not in ("high", "medium", "low"):
                conviction = "medium"

            entry_price = get_price_at(ticker, date_str)
            if not entry_price:
                continue

            trade = {
                "ticker":     ticker,
                "date":       date_str,
                "sentiment":  sentiment,
                "conviction": conviction,
                "confidence": round(confidence * 100),
                "entry":      entry_price,
                "source":     source,
                "title":      title,
                "outcomes":   {}
            }

            for hold_days in hold_days_list:
                exit_price = get_price_at(ticker, date_str, offset_days=hold_days)
                if not exit_price:
                    continue

                pct_change = round((exit_price - entry_price) / entry_price * 100, 2)

                if sentiment == "bullish":
                    result = "✅ Win" if pct_change > 2 else ("❌ Loss" if pct_change < -2 else "➡️ Flat")
                else:
                    result = "✅ Win" if pct_change < -2 else ("❌ Loss" if pct_change > 2 else "➡️ Flat")

                trade["outcomes"][f"{hold_days}d"] = {
                    "exit":       exit_price,
                    "pct_change": pct_change,
                    "result":     result
                }

            if trade["outcomes"]:
                trades.append(trade)

    return trades


# ── Summary helpers ───────────────────────────────────────────────────────────

def get_backtest_summary(trades, hold_days=7):
    """Summarize backtest results for a given hold period."""
    key = f"{hold_days}d"

    by_ticker    = defaultdict(lambda: {"wins": 0, "losses": 0, "flat": 0,
                                         "returns": [], "sentiment": ""})
    total_wins   = 0
    total_losses = 0
    total_flat   = 0
    all_returns  = []

    for trade in trades:
        outcome = trade["outcomes"].get(key)
        if not outcome:
            continue

        ticker = trade["ticker"]
        pct    = outcome["pct_change"]
        result = outcome["result"]

        by_ticker[ticker]["sentiment"] = trade["sentiment"]
        by_ticker[ticker]["returns"].append(pct)

        if "Win"  in result: by_ticker[ticker]["wins"]   += 1; total_wins   += 1
        if "Loss" in result: by_ticker[ticker]["losses"] += 1; total_losses += 1
        if "Flat" in result: by_ticker[ticker]["flat"]   += 1; total_flat   += 1

        all_returns.append(pct)

    total      = total_wins + total_losses + total_flat
    win_rate   = round(total_wins / total * 100, 1) if total > 0 else 0
    avg_return = round(sum(all_returns) / len(all_returns), 2) if all_returns else 0

    ticker_summary = []
    for ticker, s in by_ticker.items():
        t_total = s["wins"] + s["losses"] + s["flat"]
        t_wr    = round(s["wins"] / t_total * 100, 1) if t_total > 0 else 0
        t_avg   = round(sum(s["returns"]) / len(s["returns"]), 2) if s["returns"] else 0
        ticker_summary.append({
            "ticker":     ticker,
            "trades":     t_total,
            "win_rate":   t_wr,
            "avg_return": t_avg,
            "wins":       s["wins"],
            "losses":     s["losses"],
        })

    return {
        "hold_days":    hold_days,
        "total_trades": total,
        "wins":         total_wins,
        "losses":       total_losses,
        "flat":         total_flat,
        "win_rate":     win_rate,
        "avg_return":   avg_return,
        "by_ticker":    sorted(ticker_summary, key=lambda x: x["win_rate"], reverse=True)
    }


def get_all_hold_summaries(trades):
    """Return summaries for all hold periods at once."""
    return {
        hd: get_backtest_summary(trades, hold_days=hd)
        for hd in [3, 7, 14, 30]
    }


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("⏳ Running backtest (fetching prices from Yahoo Finance)...")
    trades = run_backtest()

    if not trades:
        print("❌ No trades found. Make sure reports exist and are older than today.")
    else:
        print(f"✅ Found {len(trades)} tradeable signals\n")
        print("=" * 60)
        for days in [3, 7, 14, 30]:
            s = get_backtest_summary(trades, hold_days=days)
            if s["total_trades"] == 0:
                print(f"📊 {days:2d}-Day Hold: No completed trades yet (exit date in future)")
            else:
                print(
                    f"📊 {days:2d}-Day Hold: "
                    f"{s['win_rate']}% win rate | "
                    f"Avg: {s['avg_return']:+.2f}% | "
                    f"✅{s['wins']} ❌{s['losses']} ➡️{s['flat']} "
                    f"({s['total_trades']} trades)"
                )
        print("=" * 60)

        print("\n🏷️  Per-Ticker (7-Day Hold):")
        s7 = get_backtest_summary(trades, hold_days=7)
        for t in s7["by_ticker"][:10]:
            print(
                f"  {t['ticker']:10s} "
                f"Win: {t['win_rate']:5.1f}% | "
                f"Avg: {t['avg_return']:+.2f}% | "
                f"{t['trades']} trades"
            )
