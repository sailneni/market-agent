import os, json, glob
import yfinance as yf
from datetime import datetime, timedelta
from config import REPORTS_DIR, COMMODITY_TICKERS, COMMODITY_KEYWORDS, ETF_TICKERS


def _get_price_at(ticker: str, target_date: datetime):
    try:
        sym  = COMMODITY_TICKERS.get(ticker.upper(), ticker)
        start = (target_date - timedelta(days=3)).strftime("%Y-%m-%d")
        end   = (target_date + timedelta(days=3)).strftime("%Y-%m-%d")
        hist  = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        return None


def run_backtest(reports: list = None, hold_days: int = 7) -> list:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue

    results = []
    for r in reports:
        try:
            ts = datetime.strptime(r.get("analyzed_at", "")[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        exit_date = ts + timedelta(days=hold_days)
        if exit_date > datetime.now():
            continue
        for t in r.get("analysis", {}).get("tickers", []):
            tk   = (t.get("ticker") or "").upper()
            sent = (t.get("sentiment") or "neutral").lower()
            if not tk or sent == "neutral":
                continue
            entry_price = r.get("price_data", {}).get(tk, {}).get("current_price")
            if not entry_price:
                continue
            exit_price = _get_price_at(tk, exit_date)
            if not exit_price:
                continue
            change = (exit_price - entry_price) / entry_price * 100
            correct = (sent == "bullish" and change > 0) or (sent == "bearish" and change < 0)
            results.append({
                "ticker":       tk,
                "sentiment":    sent,
                "entry_price":  entry_price,
                "exit_price":   exit_price,
                "change_pct":   round(change, 2),
                "correct":      correct,
                "hold_days":    hold_days,
                "analyzed_at":  r.get("analyzed_at", ""),
            })
    return results


def get_backtest_summary(results: list) -> dict:
    if not results:
        return {}
    correct = sum(1 for r in results if r["correct"])
    total   = len(results)
    avg_ret = round(sum(r["change_pct"] for r in results) / total, 2)
    by_ticker = {}
    for r in results:
        t = r["ticker"]
        if t not in by_ticker:
            by_ticker[t] = {"correct": 0, "total": 0, "returns": []}
        by_ticker[t]["total"] += 1
        by_ticker[t]["returns"].append(r["change_pct"])
        if r["correct"]:
            by_ticker[t]["correct"] += 1
    for t in by_ticker:
        d = by_ticker[t]
        d["win_rate"]  = round(d["correct"] / d["total"] * 100, 1)
        d["avg_return"] = round(sum(d["returns"]) / len(d["returns"]), 2)
        del d["returns"]
    return {
        "total":       total,
        "correct":     correct,
        "win_rate":    round(correct / total * 100, 1),
        "avg_return":  avg_ret,
        "by_ticker":   by_ticker,
    }
