import json
import os
import finnhub
import yfinance as yf
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
PREDICTIONS_FILE = os.path.join(BASE_DIR, "predictions.json")
EVALUATION_DAYS  = 5

COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}
COMMODITY_TICKERS  = {
    "GOLD": "GC=F", "SILVER": "SI=F",
    "XAU":  "GC=F", "XAG":   "SI=F",
    "GLD":  "GLD",  "SLV":   "SLV",
    "SVR.TO": "SVR.TO",
}

ETF_TICKERS = {
    "XEQT", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU"
}

COMMODITY_THRESHOLD = 1.0
ETF_THRESHOLD       = 1.5
STOCK_THRESHOLD     = 2.0


def get_threshold(ticker):
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS:
        return COMMODITY_THRESHOLD
    if t in ETF_TICKERS:
        return ETF_THRESHOLD
    return STOCK_THRESHOLD


def get_asset_type(ticker):
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS:
        return "commodity"
    if t in ETF_TICKERS:
        return "etf"
    return "stock"


def get_asset_icon(ticker):
    t = ticker.upper()
    if t in {"GOLD", "XAU", "GLD"}:
        return "🥇"
    if t in {"SILVER", "XAG", "SLV", "SVR.TO", "SIL", "SILJ"}:
        return "🥈"
    if t in ETF_TICKERS:
        return "📦"
    return "📈"


def load_predictions():
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE, "r") as f:
            return json.load(f)
    return []


def save_predictions(predictions):
    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(predictions, f, indent=2)


def log_prediction(ticker, sentiment, price_at_prediction, confidence,
                   video_id="", video_title=""):
    predictions = load_predictions()

    for p in predictions:
        if p["ticker"] == ticker and p["video_id"] == video_id:
            return

    predictions.append({
        "ticker":               ticker,
        "sentiment":            sentiment,
        "price_at_prediction":  price_at_prediction,
        "confidence":           confidence,
        "video_id":             video_id,
        "video_title":          video_title,
        "asset_type":           get_asset_type(ticker),
        "predicted_at":         datetime.now().isoformat(),
        "evaluate_at":          (datetime.now() + timedelta(days=EVALUATION_DAYS)).isoformat(),
        "outcome":              None,
        "actual_change_pct":    None,
        "price_at_evaluation":  None
    })

    save_predictions(predictions)
    icon = get_asset_icon(ticker)
    print(f"  📝 Logged: {icon} {ticker} → {sentiment.upper()} @ ${price_at_prediction} (threshold ±{get_threshold(ticker)}%)")


def get_current_price(ticker):
    if ticker.upper() in COMMODITY_KEYWORDS:
        try:
            yf_symbol = COMMODITY_TICKERS.get(ticker.upper(), ticker)
            hist = yf.Ticker(yf_symbol).history(period="2d")
            if not hist.empty:
                return round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
        return None

    if ticker.upper() in ETF_TICKERS:
        try:
            hist = yf.Ticker(ticker).history(period="2d")
            if not hist.empty:
                return round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
        return None

    try:
        client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))
        quote  = client.quote(ticker)
        return quote.get("c", None)
    except Exception:
        return None


def evaluate_predictions():
    predictions = load_predictions()
    now     = datetime.now()
    updated = False

    for p in predictions:
        if p["outcome"] is not None:
            continue
        if datetime.fromisoformat(p["evaluate_at"]) > now:
            continue
        if not p["price_at_prediction"]:
            continue

        try:
            current_price = get_current_price(p["ticker"])
            if not current_price:
                continue

            entry_price = p["price_at_prediction"]
            change      = ((current_price - entry_price) / entry_price) * 100
            threshold   = get_threshold(p["ticker"])

            if p["sentiment"] == "bullish":
                p["outcome"] = "correct" if change > threshold else "incorrect"
            elif p["sentiment"] == "bearish":
                p["outcome"] = "correct" if change < -threshold else "incorrect"
            else:
                p["outcome"] = "neutral"

            p["actual_change_pct"]   = round(change, 2)
            p["price_at_evaluation"] = current_price
            p["evaluated_at"]        = now.isoformat()
            updated = True

            icon   = get_asset_icon(p["ticker"])
            result = "✅" if p["outcome"] == "correct" else ("⚠️" if p["outcome"] == "neutral" else "❌")
            print(f"  {result} {icon} {p['ticker']}: predicted {p['sentiment'].upper()} → "
                  f"{p['outcome'].upper()} ({change:+.2f}% in {EVALUATION_DAYS}d, threshold ±{threshold}%)")

        except Exception as e:
            print(f"  ⚠️  Could not evaluate {p['ticker']}: {e}")

    if updated:
        save_predictions(predictions)

    return predictions


def get_accuracy_stats():
    predictions = load_predictions()
    evaluated   = [p for p in predictions if p["outcome"] in ("correct", "incorrect")]

    if not evaluated:
        return {}

    correct = sum(1 for p in evaluated if p["outcome"] == "correct")
    total   = len(evaluated)

    ticker_stats = {}
    for p in evaluated:
        t = p["ticker"]
        if t not in ticker_stats:
            ticker_stats[t] = {"correct": 0, "total": 0, "asset_type": p.get("asset_type", "stock")}
        ticker_stats[t]["total"] += 1
        if p["outcome"] == "correct":
            ticker_stats[t]["correct"] += 1
    for t in ticker_stats:
        s = ticker_stats[t]
        s["accuracy"] = round(s["correct"] / s["total"] * 100, 1)

    def split_accuracy(asset_type):
        subset = [p for p in evaluated if p.get("asset_type") == asset_type]
        if not subset:
            return None
        c = sum(1 for p in subset if p["outcome"] == "correct")
        return round(c / len(subset) * 100, 1)

    return {
        "total":               total,
        "correct":             correct,
        "accuracy":            round(correct / total * 100, 1),
        "stock_accuracy":      split_accuracy("stock"),
        "etf_accuracy":        split_accuracy("etf"),
        "commodity_accuracy":  split_accuracy("commodity"),
        "per_ticker":          ticker_stats
    }


def get_model_memory(ticker):
    predictions  = load_predictions()
    ticker_preds = [p for p in predictions if p["ticker"] == ticker and p["outcome"] in ("correct", "incorrect")]

    if not ticker_preds:
        return {"ticker": ticker, "history": "No past predictions"}

    correct  = sum(1 for p in ticker_preds if p["outcome"] == "correct")
    accuracy = round(correct / len(ticker_preds) * 100, 1)
    recent   = ticker_preds[-5:]

    return {
        "ticker":            ticker,
        "asset_type":        get_asset_type(ticker),
        "total_predictions": len(ticker_preds),
        "accuracy_pct":      accuracy,
        "threshold_used":    f"±{get_threshold(ticker)}%",
        "recent_outcomes": [
            {
                "sentiment": p["sentiment"],
                "outcome":   p["outcome"],
                "change_pct": p.get("actual_change_pct"),
                "date":      p["predicted_at"][:10]
            }
            for p in recent
        ]
    }


def print_prediction_report():
    stats = get_accuracy_stats()
    if not stats:
        print("📊 No evaluated predictions yet.")
        return

    print("\n" + "=" * 55)
    print("📊 PREDICTION PERFORMANCE REPORT")
    print("=" * 55)
    print(f"  Overall Accuracy  : {stats['accuracy']}%")
    print(f"  Total Evaluated   : {stats['total']}")
    print(f"  Correct           : {stats['correct']}")

    if stats.get("stock_accuracy")     is not None: print(f"\n  📈 Stock Accuracy     : {stats['stock_accuracy']}%")
    if stats.get("etf_accuracy")       is not None: print(f"  📦 ETF Accuracy       : {stats['etf_accuracy']}%")
    if stats.get("commodity_accuracy") is not None: print(f"  🥇 Commodity Accuracy : {stats['commodity_accuracy']}%")

    print(f"\n  Per-Ticker Breakdown:")
    for ticker, s in sorted(stats["per_ticker"].items(), key=lambda x: x[1]["accuracy"], reverse=True):
        icon = get_asset_icon(ticker)
        bar  = "█" * int(s["accuracy"] / 10)
        print(f"    {icon} {ticker:<10} {s['accuracy']:>5.1f}%  {bar}  ({s['correct']}/{s['total']})")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    print_prediction_report()
