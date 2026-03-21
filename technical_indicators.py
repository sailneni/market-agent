import yfinance as yf
import pandas as pd


CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LINK", "LTC", "UNI", "ATOM", "XLM", "ALGO",
    "VET", "FIL", "AAVE", "COMP", "SHIB", "TRX", "ETC", "BCH",
    "APT", "ARB", "OP", "INJ", "SUI", "SEI", "TIA", "PEPE"
}


def normalize_ticker(ticker):
    upper = ticker.upper().strip()
    if upper in CRYPTO_TICKERS and not upper.endswith("-USD"):
        return f"{upper}-USD"
    return upper


def get_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def get_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd_line": round(float(macd_line.iloc[-1]), 4),
        "signal_line": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
        "crossover": "bullish" if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) else "bearish"
    }


def get_moving_averages(series):
    return {
        "ma_20": round(float(series.rolling(window=20).mean().iloc[-1]), 2),
        "ma_50": round(float(series.rolling(window=50).mean().iloc[-1]), 2),
        "ma_200": round(float(series.rolling(window=200).mean().iloc[-1]), 2),
    }


def get_bollinger_bands(series, period=20):
    ma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = ma + (2 * std)
    lower = ma - (2 * std)
    current_price = float(series.iloc[-1])
    upper_val = round(float(upper.iloc[-1]), 2)
    lower_val = round(float(lower.iloc[-1]), 2)

    if current_price > upper_val:
        position = "above_upper — overbought"
    elif current_price < lower_val:
        position = "below_lower — oversold"
    else:
        position = "inside_bands — neutral"

    return {
        "upper_band": upper_val,
        "lower_band": lower_val,
        "position": position
    }


def get_volume_analysis(df):
    avg_volume = float(df["Volume"].rolling(window=20).mean().iloc[-1])
    latest_volume = float(df["Volume"].iloc[-1])
    ratio = round(latest_volume / avg_volume, 2) if avg_volume else 0

    if ratio >= 2.0:
        signal = "🔥 Very High Volume — strong conviction move"
    elif ratio >= 1.5:
        signal = "📈 High Volume — above average interest"
    elif ratio <= 0.5:
        signal = "😴 Low Volume — weak move, no conviction"
    else:
        signal = "📊 Normal Volume"

    return {
        "latest_volume": int(latest_volume),
        "avg_volume_20d": int(avg_volume),
        "volume_ratio": ratio,
        "signal": signal
    }


def get_trend_signal(price, ma_20, ma_50, ma_200):
    signals = []
    if price > ma_200:
        signals.append("above 200MA")
    else:
        signals.append("below 200MA")

    if price > ma_50:
        signals.append("above 50MA")
    else:
        signals.append("below 50MA")

    if ma_20 > ma_50:
        signals.append("golden cross potential")
    else:
        signals.append("death cross potential")

    bullish_count = sum(1 for s in signals if "above" in s or "golden" in s)

    if bullish_count == 3:
        trend = "STRONG UPTREND 🟢"
    elif bullish_count == 2:
        trend = "MODERATE UPTREND 🟡"
    elif bullish_count == 1:
        trend = "MODERATE DOWNTREND 🟠"
    else:
        trend = "STRONG DOWNTREND 🔴"

    return {"trend": trend, "signals": signals}


def get_support_resistance(series, lookback=60):
    recent = series.tail(lookback)
    support = round(float(recent.min()), 2)
    resistance = round(float(recent.max()), 2)
    current = float(series.iloc[-1])
    pct_to_resistance = round(((resistance - current) / current) * 100, 2)
    pct_to_support = round(((current - support) / current) * 100, 2)
    return {
        "support": support,
        "resistance": resistance,
        "pct_to_resistance": pct_to_resistance,
        "pct_to_support": pct_to_support
    }


def interpret_rsi(rsi):
    if rsi >= 70:
        return "OVERBOUGHT 🔴 — consider waiting for pullback"
    elif rsi >= 60:
        return "STRONG 🟠 — bullish but getting stretched"
    elif rsi >= 40:
        return "NEUTRAL 🟡 — no clear signal"
    elif rsi >= 30:
        return "WEAK 🔵 — bearish momentum"
    else:
        return "OVERSOLD 🟢 — potential bounce/buy zone"


def get_technical_indicators(ticker):
    print(f"  📊 Fetching technical indicators for {ticker}...")
    try:
        yf_ticker = normalize_ticker(ticker)
        if yf_ticker != ticker:
            print(f"  🔄 Crypto detected — using {yf_ticker}")

        df = yf.download(yf_ticker, period="1y", interval="1d", progress=False, auto_adjust=True)

        if df.empty or len(df) < 30:
            return {"error": f"Not enough data for {yf_ticker}"}

        # ── Fix multi-level columns from yfinance ──────────────
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"].astype(float)
        current_price = round(float(close.iloc[-1]), 2)

        rsi = get_rsi(close)
        macd = get_macd(close)
        mas = get_moving_averages(close)
        bb = get_bollinger_bands(close)
        volume = get_volume_analysis(df)
        trend = get_trend_signal(current_price, mas["ma_20"], mas["ma_50"], mas["ma_200"])
        support_resistance = get_support_resistance(close)

        # ── Overall technical score ─────────────────────────────
        score = 0
        if rsi < 35:
            score += 2
        elif rsi < 50:
            score += 1
        elif rsi > 70:
            score -= 2
        elif rsi > 60:
            score -= 1

        if macd["crossover"] == "bullish":
            score += 2
        else:
            score -= 2

        if current_price > mas["ma_50"]:
            score += 1
        else:
            score -= 1

        if current_price > mas["ma_200"]:
            score += 1
        else:
            score -= 1

        if volume["volume_ratio"] >= 1.5:
            score += 1

        if score >= 4:
            overall = "STRONG BUY 🟢"
        elif score >= 2:
            overall = "BUY 🟢"
        elif score >= 0:
            overall = "NEUTRAL 🟡"
        elif score >= -2:
            overall = "SELL 🔴"
        else:
            overall = "STRONG SELL 🔴"

        return {
            "ticker": ticker,           # keep original ticker label e.g. BTC not BTC-USD
            "yf_ticker": yf_ticker,     # store the resolved yfinance ticker
            "current_price": current_price,
            "rsi": {
                "value": rsi,
                "interpretation": interpret_rsi(rsi)
            },
            "macd": macd,
            "moving_averages": mas,
            "bollinger_bands": bb,
            "volume": volume,
            "trend": trend,
            "support_resistance": support_resistance,
            "technical_score": score,
            "overall_signal": overall
        }

    except Exception as e:
        print(f"  ⚠️  Technical indicators failed for {ticker}: {e}")
        return {"error": str(e)}


def print_technical_report(ticker, data):
    if "error" in data:
        print(f"  ❌ {ticker}: {data['error']}")
        return

    print(f"\n  📊 TECHNICAL ANALYSIS — {ticker}")
    print(f"  {'─' * 45}")
    print(f"  Current Price      : ${data['current_price']}")
    print(f"  Overall Signal     : {data['overall_signal']}")
    print(f"  Technical Score    : {data['technical_score']}/7")

    rsi = data["rsi"]
    print(f"\n  RSI (14)           : {rsi['value']} — {rsi['interpretation']}")

    macd = data["macd"]
    print(f"  MACD               : {macd['macd_line']} | Signal: {macd['signal_line']}")
    print(f"  MACD Crossover     : {macd['crossover'].upper()}")
    print(f"  Histogram          : {macd['histogram']}")

    mas = data["moving_averages"]
    print(f"\n  MA 20              : ${mas['ma_20']}")
    print(f"  MA 50              : ${mas['ma_50']}")
    print(f"  MA 200             : ${mas['ma_200']}")

    trend = data["trend"]
    print(f"\n  Trend              : {trend['trend']}")
    for s in trend["signals"]:
        print(f"    • {s}")

    bb = data["bollinger_bands"]
    print(f"\n  Bollinger Bands    : Upper ${bb['upper_band']} | Lower ${bb['lower_band']}")
    print(f"  BB Position        : {bb['position']}")

    sr = data["support_resistance"]
    print(f"\n  Support (60d low)  : ${sr['support']} ({sr['pct_to_support']}% below price)")
    print(f"  Resistance (60d)   : ${sr['resistance']} ({sr['pct_to_resistance']}% above price)")

    vol = data["volume"]
    print(f"\n  Latest Volume      : {vol['latest_volume']:,}")
    print(f"  Avg Volume (20d)   : {vol['avg_volume_20d']:,}")
    print(f"  Volume Ratio       : {vol['volume_ratio']}x — {vol['signal']}")


# ── Quick test ────────────────────────────────────────────
if __name__ == "__main__":
    test_tickers = ["NVDA", "AAPL", "BTC", "ETH"]
    for ticker in test_tickers:
        data = get_technical_indicators(ticker)
        print_technical_report(ticker, data)
        print()
