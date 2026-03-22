import json, os, finnhub
import yfinance as yf
from datetime import datetime, timedelta
from config import BASE_DIR, FINNHUB_API_KEY, COMMODITY_KEYWORDS, COMMODITY_TICKERS, ETF_TICKERS, EVAL_DAYS

PREDICTIONS_FILE = os.path.join(BASE_DIR, "predictions.json")

COMMODITY_THRESHOLD = 1.0
ETF_THRESHOLD       = 1.5
STOCK_THRESHOLD     = 2.0


def get_asset_type(ticker: str) -> str:
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS: return "commodity"
    if t in ETF_TICKERS:        return "etf"
    return "stock"


def get_asset_icon(ticker: str) -> str:
    t = ticker.upper()
    if t in {"GOLD", "XAU", "GLD"}:                        return "🥇"
    if t in {"SILVER", "XAG", "SLV", "SVR.TO", "SIL", "SILJ"}: return "🥈"
    if t in ETF_TICKERS:                                    return "📦"
    return "📈"


def get_threshold(ticker: str) -> float:
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS: return COMMODITY_THRESHOLD
    if t in ETF_TICKERS:        return ETF_THRESHOLD
    return STOCK_THRESHOLD


def load_predictions() -> list:
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE) as f:
            return json.load(f)
    return []


def save_predictions(predictions: list):
    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(predictions, f, indent=2)


def log_prediction(ticker, sentiment, price_at_prediction, confidence,
                   video_id="", video_title=""):
    predictions = load_predictions()
    if any(p["ticker"] == ticker and p["video_id"] == video_id for p in predictions):
        return
    predictions.append({
        "ticker":              ticker,
        "sentiment":           sentiment,
        "price_at_prediction": price_at_prediction,
        "confidence":          confidence,
        "video_id":            video_id,
        "video_title":         video_title,
        "asset_type":          get_asset_type(ticker),
        "predicted_at":        datetime.now().isoformat(),
        "evaluate_at":         (datetime.now() + timedelta(days=EVAL_DAYS)).isoformat(),
        "outcome":             None,
        "actual_change_pct":   None,
        "price_at_evaluation": None,
    })
    save_predictions(predictions)
    icon = get_asset_icon(ticker)
    print(f"  📝 Logged: {icon} {ticker} → {sentiment.upper()} @ ${price_at_prediction}")


def _get_current_price(ticker: str):
    t = ticker.upper()
    if t in COMMODITY_KEYWORDS:
        sym  = COMMODITY_TICKERS.get(t, t)
        hist = yf.Ticker(sym).history(period="2d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else None
    if t in ETF_TICKERS:
        hist = yf.Ticker(ticker).history(period="2d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else None
    try:
        q = finnhub.Client(api_key=FINNHUB_API_KEY).quote(ticker)
        return q.get("c")
    except Exception:
        return None


def evaluate_predictions():
    predictions = load_predictions()
    now = datetime.now()
    updated = False
    for p in predictions:
        if p["outcome"] is not None:
            continue
        if datetime.fromisoformat(p["evaluate_at"]) > now:
            continue
        if not p["price_at_prediction"]:
            continue
        try:
            cur = _get_current_price(p["ticker"])
            if not cur:
                continue
            change    = (cur - p["price_at_prediction"]) / p["price_at_prediction"] * 100
            threshold = get_threshold(p["ticker"])
            if p["sentiment"] == "bullish":
                p["outcome"] = "correct" if change > threshold else "incorrect"
            elif p["sentiment"] == "bearish":
                p["outcome"] = "correct" if change < -threshold else "incorrect"
            else:
                p["outcome"] = "neutral"
            p["actual_change_pct"]   = round(change, 2)
            p["price_at_evaluation"] = cur
            p["evaluated_at"]        = now.isoformat()
            updated = True
        except Exception as e:
            print(f"  ⚠️  Could not evaluate {p['ticker']}: {e}")
    if updated:
        save_predictions(predictions)
    return predictions


def get_accuracy_stats() -> dict:
    predictions = load_predictions()
    evaluated   = [p for p in predictions if p["outcome"] in ("correct", "incorrect")]
    if not evaluated:
        return {}
    correct = sum(1 for p in evaluated if p["outcome"] == "correct")
    total   = len(evaluated)
    def split(atype):
        sub = [p for p in evaluated if p.get("asset_type") == atype]
        if not sub: return None
        return round(sum(1 for p in sub if p["outcome"] == "correct") / len(sub) * 100, 1)
    return {
        "total": total, "correct": correct,
        "accuracy":           round(correct / total * 100, 1),
        "stock_accuracy":     split("stock"),
        "etf_accuracy":       split("etf"),
        "commodity_accuracy": split("commodity"),
    }


def get_model_memory(ticker: str) -> dict:
    preds = [p for p in load_predictions()
             if p["ticker"] == ticker and p["outcome"] in ("correct", "incorrect")]
    if not preds:
        return {"ticker": ticker, "history": "No past predictions"}
    correct  = sum(1 for p in preds if p["outcome"] == "correct")
    return {
        "ticker":            ticker,
        "asset_type":        get_asset_type(ticker),
        "total_predictions": len(preds),
        "accuracy_pct":      round(correct / len(preds) * 100, 1),
        "threshold_used":    f"±{get_threshold(ticker)}%",
        "recent_outcomes": [
            {"sentiment": p["sentiment"], "outcome": p["outcome"],
             "change_pct": p.get("actual_change_pct"), "date": p["predicted_at"][:10]}
            for p in preds[-5:]
        ],
    }


def print_prediction_report():
    stats = get_accuracy_stats()
    if not stats:
        print("📊 No evaluated predictions yet.")
        return
    print(f"\n{'='*55}\n📊 PREDICTION PERFORMANCE REPORT\n{'='*55}")
    print(f"  Overall Accuracy : {stats['accuracy']}% ({stats['correct']}/{stats['total']})")
    if stats.get("stock_accuracy")     is not None: print(f"  📈 Stocks     : {stats['stock_accuracy']}%")
    if stats.get("etf_accuracy")       is not None: print(f"  📦 ETFs       : {stats['etf_accuracy']}%")
    if stats.get("commodity_accuracy") is not None: print(f"  🥇 Commodities: {stats['commodity_accuracy']}%")
