import yfinance as yf
import pandas as pd

CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LINK", "LTC", "UNI", "ATOM", "XLM", "ALGO",
    "VET", "FIL", "AAVE", "COMP", "SHIB", "TRX", "ETC", "BCH",
    "APT", "ARB", "OP", "INJ", "SUI", "SEI", "TIA", "PEPE",
}


def _normalize(ticker: str) -> str:
    t = ticker.upper().strip()
    return f"{t}-USD" if t in CRYPTO_TICKERS and not t.endswith("-USD") else t


def _rsi(series, period=14) -> float:
    delta    = series.diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs       = avg_gain / avg_loss
    return round(float((100 - (100 / (1 + rs))).iloc[-1]), 2)


def _macd(series, fast=12, slow=26, signal=9) -> dict:
    ema_f = series.ewm(span=fast, adjust=False).mean()
    ema_s = series.ewm(span=slow, adjust=False).mean()
    line  = ema_f - ema_s
    sig   = line.ewm(span=signal, adjust=False).mean()
    hist  = line - sig
    return {
        "macd_line":   round(float(line.iloc[-1]), 4),
        "signal_line": round(float(sig.iloc[-1]),  4),
        "histogram":   round(float(hist.iloc[-1]), 4),
        "crossover":   "bullish" if float(line.iloc[-1]) > float(sig.iloc[-1]) else "bearish",
    }


def _moving_averages(series) -> dict:
    return {
        "ma_20":  round(float(series.rolling(20).mean().iloc[-1]), 2),
        "ma_50":  round(float(series.rolling(50).mean().iloc[-1]), 2),
        "ma_200": round(float(series.rolling(200).mean().iloc[-1]), 2),
    }


def _bollinger(series, period=20) -> dict:
    ma    = series.rolling(period).mean()
    std   = series.rolling(period).std()
    upper = round(float((ma + 2 * std).iloc[-1]), 2)
    lower = round(float((ma - 2 * std).iloc[-1]), 2)
    price = float(series.iloc[-1])
    pos   = ("above_upper — overbought" if price > upper
             else "below_lower — oversold" if price < lower
             else "inside_bands — neutral")
    return {"upper_band": upper, "lower_band": lower, "position": pos}


def _volume(df) -> dict:
    avg    = float(df["Volume"].rolling(20).mean().iloc[-1])
    latest = float(df["Volume"].iloc[-1])
    ratio  = round(latest / avg, 2) if avg else 0
    sig    = ("🔥 Very High Volume" if ratio >= 2.0
              else "📈 High Volume" if ratio >= 1.5
              else "😴 Low Volume" if ratio <= 0.5
              else "📊 Normal Volume")
    return {"latest_volume": int(latest), "avg_volume_20d": int(avg),
            "volume_ratio": ratio, "signal": sig}


def _support_resistance(series, lookback=60) -> dict:
    recent = series.tail(lookback)
    cur    = float(series.iloc[-1])
    sup    = round(float(recent.min()), 2)
    res    = round(float(recent.max()), 2)
    return {
        "support":            sup,
        "resistance":         res,
        "pct_to_resistance":  round((res - cur) / cur * 100, 2),
        "pct_to_support":     round((cur - sup) / cur * 100, 2),
    }


def get_technicals(ticker: str) -> dict:
    try:
        yf_ticker = _normalize(ticker)
        df = yf.download(yf_ticker, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            return {"error": f"Not enough data for {yf_ticker}"}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"].astype(float)
        price = round(float(close.iloc[-1]), 2)
        rsi   = _rsi(close)
        macd  = _macd(close)
        mas   = _moving_averages(close)
        bb    = _bollinger(close)
        vol   = _volume(df)
        sr    = _support_resistance(close)

        score = 0
        score += 2 if rsi < 35 else 1 if rsi < 50 else -2 if rsi > 70 else -1 if rsi > 60 else 0
        score += 2 if macd["crossover"] == "bullish" else -2
        score += 1 if price > mas["ma_50"]  else -1
        score += 1 if price > mas["ma_200"] else -1
        score += 1 if vol["volume_ratio"] >= 1.5 else 0

        signal = ("STRONG BUY 🟢" if score >= 4 else "BUY 🟢" if score >= 2
                  else "NEUTRAL 🟡" if score >= 0 else "SELL 🔴" if score >= -2
                  else "STRONG SELL 🔴")

        return {
            "ticker": ticker, "yf_ticker": yf_ticker,
            "current_price": price,
            "rsi":               {"value": rsi},
            "macd":              macd,
            "moving_averages":   mas,
            "bollinger_bands":   bb,
            "volume":            vol,
            "support_resistance": sr,
            "technical_score":   score,
            "overall_signal":    signal,
        }
    except Exception as e:
        return {"error": str(e)}
