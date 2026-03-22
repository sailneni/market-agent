import streamlit as st
import json
import os
import glob
import sys
from datetime import datetime
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from prediction_tracker import (
    log_prediction, evaluate_predictions,
    get_accuracy_stats, get_model_memory,
    load_predictions, print_prediction_report,
    get_asset_type, get_asset_icon
)
from signal_scorer import score_ticker, score_all_tickers
from watchlist_learner import get_top_tickers, save_watchlist
from contradiction_detector import detect_contradictions
from sector_rotation import build_rotation_data, get_sector_summary
from trend_detector import detect_trending_tickers
from backtester import run_backtest, get_backtest_summary


COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}

ETF_TICKERS = {
    "XEQT.TO", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU"
}

YOUR_ETFS   = ["XEQT.TO", "VDY", "SMH", "CHPS", "SIL", "SVR.TO", "CASH.TO"]
MARKET_ETFS = {"SPY": "S&P 500", "QQQ": "NASDAQ 100", "VTI": "Total US Market", "VFV": "S&P 500 (CAD)"}
SECTOR_ETFS = {
    "SMH":  "Semiconductors", "CHPS": "Chips",
    "XLK":  "Technology",     "XLF":  "Financials",
    "XLE":  "Energy",         "XLV":  "Health Care",
    "XLU":  "Utilities",      "SIL":  "Silver Miners"
}


def ticker_icon(ticker):
    t = ticker.upper()
    if t in {"GOLD", "XAU"}:                         return "🥇"
    if t in {"SILVER", "XAG", "SLV",
             "SVR.TO", "SIL", "SILJ"}:               return "🥈"
    if t in ETF_TICKERS:                              return "📦"
    return ""


def sentiment_color(sentiment):
    s = str(sentiment).lower()
    if s == "bullish": return "🟢"
    if s == "bearish": return "🔴"
    return "🟡"


def tech_badge(signal):
    if not signal or signal == "N/A": return "⚪ N/A"
    s = signal.lower()
    if "strong buy"  in s: return f"🟢🟢 {signal}"
    if "buy"         in s: return f"🟢 {signal}"
    if "strong sell" in s: return f"🔴🔴 {signal}"
    if "sell"        in s: return f"🔴 {signal}"
    return f"🟡 {signal}"


def yf_price(symbol):
    try:
        hist  = yf.Ticker(symbol).history(period="2d")
        if hist.empty:
            return None, None
        price = round(float(hist["Close"].iloc[-1]), 2)
        prev  = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else price
        chg   = round(((price - prev) / prev) * 100, 2)
        return price, chg
    except Exception:
        return None, None


st.set_page_config(
    page_title="Market Intelligence Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26;
        border-radius: 12px;
        padding: 20px;
        margin: 8px 0;
        border-left: 4px solid #00d4aa;
    }
</style>
""", unsafe_allow_html=True)


# ── Report loader: DB first, JSON fallback ────────────────────────────────────

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
                SELECT r.id, r.video_id, r.analyzed_at, r.channel, r.title,
                       r.confidence, r.overall_sentiment,
                       r.price_data, r.news_data, r.tech_data, r.market_context,
                       s.ticker, s.sentiment, s.conviction, s.context_text, s.company
                FROM reports r
                LEFT JOIN signals s ON s.report_id = r.id
                ORDER BY r.analyzed_at DESC
                LIMIT 500
            """)).fetchall()

        for row in rows:
            rid = row[0]
            if rid not in report_map:
                report_map[rid] = {
                    "_db_id":      rid,
                    "_filename":   "",
                    "analyzed_at": row[2].strftime("%Y%m%d_%H%M%S") if row[2] else "",
                    "video": {
                        "video_id":     row[1] or "",
                        "channel":      row[3] or "N/A",
                        "title":        row[4] or "",
                        "published_at": row[2].isoformat() if row[2] else ""
                    },
                    "analysis": {
                        "confidence_score":        float(row[5]) if row[5] else 0,
                        "overall_market_sentiment": row[6] or "neutral",
                        "tickers": [],
                        "key_themes":        [],
                        "bull_cases":        [],
                        "bear_cases":        [],
                        "investment_tactics": []
                    },
                    "price_data":     row[7]  if isinstance(row[7],  dict) else {},
                    "news_data":      row[8]  if isinstance(row[8],  dict) else {},
                    "tech_data":      row[9]  if isinstance(row[9],  dict) else {},
                    "market_context": row[10] if isinstance(row[10], dict) else {}
                }
            if row[11]:  # ticker
                report_map[rid]["analysis"]["tickers"].append({
                    "ticker":     row[11],
                    "sentiment":  row[12] or "neutral",
                    "conviction": row[13] or "medium",
                    "context":    row[14] or "",
                    "company":    row[15] or ""
                })

        return list(report_map.values())
    except Exception as e:
        st.caption(f"⚠️ DB unavailable ({e}) — using JSON files")
        return None


def _load_reports_from_json():
    reports = []
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                data = json.load(f)
                data["_filename"] = file
                reports.append(data)
        except Exception:
            continue
    return reports


@st.cache_data(ttl=120)
def load_reports():
    if os.environ.get("DATABASE_URL"):
        result = _load_reports_from_db()
        if result is not None:
            return result
    return _load_reports_from_json()


# ── Sidebar ────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=60)
    st.title("Market Intelligence")
    st.markdown("---")

    reports = load_reports()
    st.metric("📁 Total Reports", len(reports))

    if reports:
        all_tickers        = []
        commodity_mentions = 0
        etf_mentions       = 0
        for r in reports:
            for t in r.get("analysis", {}).get("tickers", []):
                tk = t.get("ticker")
                if tk:
                    all_tickers.append(tk)
                    if tk.upper() in COMMODITY_KEYWORDS: commodity_mentions += 1
                    if tk.upper() in ETF_TICKERS:        etf_mentions       += 1

        st.metric("📌 Unique Tickers", len(set(all_tickers)))
        bullish = sum(1 for r in reports if r.get("analysis", {}).get("overall_market_sentiment", "").lower() == "bullish")
        bearish = sum(1 for r in reports if r.get("analysis", {}).get("overall_market_sentiment", "").lower() == "bearish")
        st.metric("🟢 Bullish Reports", bullish)
        st.metric("🔴 Bearish Reports", bearish)
        if commodity_mentions: st.metric("🥇 Commodity Mentions", commodity_mentions)
        if etf_mentions:       st.metric("📦 ETF Mentions",       etf_mentions)

        for r in reports:
            fg = r.get("market_context", {}).get("fear_and_greed", {})
            if fg and "error" not in fg:
                st.markdown("---")
                st.markdown("**😨 Fear & Greed**")
                st.markdown(f"`{fg.get('score')}/100` — {fg.get('rating', '').upper()}")
                break

    stats = get_accuracy_stats()
    if stats:
        st.markdown("---")
        st.markdown("**🧠 Prediction Accuracy**")
        st.metric("Overall", f"{stats['accuracy']}%", f"{stats['correct']}/{stats['total']} correct")
        if stats.get("stock_accuracy")     is not None: st.caption(f"📈 Stocks: {stats['stock_accuracy']}%")
        if stats.get("etf_accuracy")       is not None: st.caption(f"📦 ETFs: {stats['etf_accuracy']}%")
        if stats.get("commodity_accuracy") is not None: st.caption(f"🥇 Commodities: {stats['commodity_accuracy']}%")

    st.markdown("---")
    page = st.radio("Navigate", [
        "🏠 Dashboard",
        "📋 All Reports",
        "🔍 Ticker Search",
        "📊 Technical View",
        "🌍 Market Context",
        "🧠 Prediction Tracker",
        "🥇 Commodities",
        "📦 ETFs",
        "🔔 Signal Scores",
        "🔥 Auto Watchlist",
        "⚠️ Contradictions",
        "🌡️ Sector Rotation",
        "📈 Trend Detection",
        "🔁 Backtest",
        "📧 Daily Digest",
        "▶️ Analyze Video"
    ])
    st.markdown("---")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ═══════════════════════════════════════════════════════════
if page == "🏠 Dashboard":
    st.title("📊 Market Intelligence Dashboard")
    st.markdown(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    st.markdown("---")

    if not reports:
        st.warning("⚠️ No reports found yet. Run `python feed_watcher.py` to start.")
        st.info(f"📂 Looking in: `{REPORTS_DIR}`")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("📁 Total Reports", len(reports))
        with col2:
            avg_conf = sum(r.get("analysis", {}).get("confidence_score", 0) for r in reports) / len(reports)
            st.metric("🎯 Avg Confidence", f"{avg_conf * 100:.0f}%")
        with col3:
            bullish = sum(1 for r in reports if r.get("analysis", {}).get("overall_market_sentiment", "").lower() == "bullish")
            st.metric("🟢 Bullish", bullish)
        with col4:
            bearish = sum(1 for r in reports if r.get("analysis", {}).get("overall_market_sentiment", "").lower() == "bearish")
            st.metric("🔴 Bearish", bearish)

        st.markdown("---")
        pc = st.columns(6)
        for col, sym, label in [
            (pc[0], "GC=F",    "🥇 Gold"),
            (pc[1], "SI=F",    "🥈 Silver"),
            (pc[2], "XEQT.TO",   "📦 XEQT.TO"),
            (pc[3], "SMH",    "📦 SMH"),
            (pc[4], "SIL",    "📦 SIL"),
            (pc[5], "SVR.TO", "📦 SVR.TO"),
        ]:
            price, chg = yf_price(sym)
            if price:
                col.metric(label, f"${price:,}", f"{chg:+.2f}%")
            else:
                col.metric(label, "N/A")

        if stats:
            st.markdown("---")
            acc = stats["accuracy"]
            msg = f"🧠 **Model Accuracy: {acc}%** — {stats['correct']}/{stats['total']} predictions correct"
            if acc >= 70:   st.success(msg)
            elif acc >= 50: st.warning(msg)
            else:           st.error(msg)

        for r in reports:
            fg = r.get("market_context", {}).get("fear_and_greed", {})
            if fg and "error" not in fg:
                score = fg.get("score", 0)
                st.markdown("---")
                msg = f"😨 **Fear & Greed Index: {score}/100** — {fg.get('signal')}"
                if score <= 25:   st.error(msg)
                elif score <= 45: st.warning(msg)
                elif score <= 55: st.info(msg)
                else:             st.success(msg)
                break

        st.markdown("---")
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("📈 Sentiment Overview")
            neutral = len(reports) - bullish - bearish
            st.bar_chart(pd.DataFrame({
                "Sentiment": ["Bullish", "Bearish", "Neutral"],
                "Count":     [bullish, bearish, neutral]
            }).set_index("Sentiment"))

        with col_right:
            st.subheader("🏷️ Most Mentioned Tickers")
            ticker_counts = {}
            for r in reports:
                for t in r.get("analysis", {}).get("tickers", []):
                    tk = t.get("ticker")
                    if tk:
                        icon  = ticker_icon(tk)
                        label = f"{icon}{tk}" if icon else tk
                        ticker_counts[label] = ticker_counts.get(label, 0) + 1
            if ticker_counts:
                ticker_df = pd.DataFrame(
                    list(ticker_counts.items()), columns=["Ticker", "Mentions"]
                ).sort_values("Mentions", ascending=False).head(10)
                st.bar_chart(ticker_df.set_index("Ticker"))

        st.markdown("---")
        st.subheader("🕐 Latest Reports")
        for report in reports[:5]:
            video      = report.get("video", {})
            analysis   = report.get("analysis", {})
            sentiment  = analysis.get("overall_market_sentiment", "neutral")
            confidence = analysis.get("confidence_score", 0) * 100
            tickers    = [t.get("ticker") for t in analysis.get("tickers", []) if t.get("ticker")]
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.markdown(f"**{video.get('title', 'Unknown')[:70]}**")
                st.caption(f"📡 {video.get('channel', 'N/A')} • 🕐 {report.get('analyzed_at', 'N/A')}")
            with col2:
                st.markdown(f"{sentiment_color(sentiment)} {sentiment.upper()}")
            with col3:
                st.markdown(f"🎯 {confidence:.0f}%")
            with col4:
                labels = [f"{ticker_icon(t)}{t}" if ticker_icon(t) else t for t in tickers[:3]]
                st.markdown(f"`{'` `'.join(labels)}`" if labels else "No tickers")
            st.markdown("---")


# ═══════════════════════════════════════════════════════════
# PAGE 2 — ALL REPORTS
# ═══════════════════════════════════════════════════════════
elif page == "📋 All Reports":
    st.title("📋 All Reports")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        for i, report in enumerate(reports):
            video      = report.get("video", {})
            analysis   = report.get("analysis", {})
            sentiment  = analysis.get("overall_market_sentiment", "neutral")
            confidence = analysis.get("confidence_score", 0) * 100
            tickers    = analysis.get("tickers", [])
            price_data = report.get("price_data", {})
            news_data  = report.get("news_data",  {})
            tech_data  = report.get("tech_data",  {})
            market_ctx = report.get("market_context", {})

            with st.expander(
                f"{sentiment_color(sentiment)} {video.get('title', 'Unknown')[:80]} — {confidence:.0f}% confidence",
                expanded=(i == 0)
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**📡 Source:** {video.get('channel', 'N/A')}")
                    url = video.get("url") or f"https://youtube.com/watch?v={video.get('video_id', '')}"
                    st.markdown(f"**🔗 URL:** [Open]({url})")
                    st.markdown(f"**📈 Sentiment:** {sentiment_color(sentiment)} {sentiment.upper()}")
                    st.markdown(f"**🎯 Confidence:** {confidence:.0f}%")
                    fg = market_ctx.get("fear_and_greed", {})
                    if fg and "error" not in fg:
                        st.markdown(f"**😨 Fear & Greed:** `{fg.get('score')}/100` — {fg.get('signal')}")

                with col2:
                    if tickers:
                        st.markdown("**📌 Tickers:**")
                        for t in tickers:
                            tk           = t.get("ticker", "")
                            icon         = ticker_icon(tk)
                            price        = price_data.get(tk, {})
                            change       = price.get("change_pct", "N/A")
                            arrow        = "🔺" if isinstance(change, float) and change > 0 else "🔻"
                            is_commodity = tk.upper() in COMMODITY_KEYWORDS
                            is_etf       = tk.upper() in ETF_TICKERS
                            news         = news_data.get(tk, {})
                            news_sent    = news.get("news_sentiment", {}).get("sentiment", "N/A")
                            tech         = tech_data.get(tk, {})
                            tech_ok      = tech and "error" not in tech and "skipped" not in tech
                            tech_sig     = tech.get("overall_signal", "N/A") if tech_ok else ("ETF" if is_etf else "Commodity" if is_commodity else "N/A")
                            rsi_val      = tech.get("rsi", {}).get("value", "N/A") if tech_ok else "N/A"
                            st.markdown(f"`{icon}{tk}` ${price.get('current_price', 'N/A')} {arrow}{change}%")
                            st.caption(f"📰 {news_sent} | 📊 {tech_sig} | RSI: {rsi_val}")
                            if not is_commodity and not is_etf:
                                ec = market_ctx.get("earnings_calendar", {}).get(tk, {})
                                if ec and "error" not in ec and "status" not in ec:
                                    st.caption(f"📅 Earnings: {ec.get('date')} ({ec.get('urgency')})")
                                it = market_ctx.get("insider_trading", {}).get(tk, {})
                                if it and "error" not in it:
                                    st.caption(f"🏦 {it.get('signal')}")

                themes = analysis.get("key_themes", [])
                if themes:
                    st.markdown("**🔑 Key Themes:** " + " • ".join(themes[:5]))

                col3, col4 = st.columns(2)
                with col3:
                    bulls = analysis.get("bull_cases", [])
                    if bulls:
                        st.markdown("**🟢 Bull Cases:**")
                        for b in bulls[:3]: st.markdown(f"• {b}")
                with col4:
                    bears = analysis.get("bear_cases", [])
                    if bears:
                        st.markdown("**🔴 Bear Cases:**")
                        for b in bears[:3]: st.markdown(f"• {b}")

                tactics = analysis.get("investment_tactics", [])
                if tactics:
                    st.markdown("**💡 Investment Tactics:**")
                    for tac in tactics[:4]: st.markdown(f"• {tac}")

                if news_data:
                    st.markdown("**📰 Latest Headlines:**")
                    for t in tickers:
                        tk       = t.get("ticker", "")
                        articles = news_data.get(tk, {}).get("articles", [])
                        if articles:
                            st.markdown(f"*{ticker_icon(tk)}{tk}:*")
                            for article in articles[:3]:
                                if "error" not in article:
                                    st.markdown(f"  • [{article.get('source')}] {article.get('title', '')[:70]}")


# ═══════════════════════════════════════════════════════════
# PAGE 3 — TICKER SEARCH
# ═══════════════════════════════════════════════════════════
elif page == "🔍 Ticker Search":
    st.title("🔍 Ticker Search")
    st.markdown("---")

    search_ticker = st.text_input("Enter ticker (e.g. AAPL, NVDA, GOLD, SILVER, XEQT, SMH)").upper().strip()

    if search_ticker:
        is_commodity = search_ticker in COMMODITY_KEYWORDS
        is_etf       = search_ticker in ETF_TICKERS
        icon         = ticker_icon(search_ticker)
        asset_type   = get_asset_type(search_ticker)

        matches = [
            {"report": r, "ticker_data": t}
            for r in reports
            for t in r.get("analysis", {}).get("tickers", [])
            if t.get("ticker", "").upper() == search_ticker
        ]

        if not matches:
            st.warning(f"No reports found mentioning **{icon}{search_ticker}**")
        else:
            st.success(f"Found **{len(matches)}** report(s) mentioning {icon}{search_ticker} ({asset_type.upper()})")

            sentiments = [m["ticker_data"].get("sentiment", "neutral") for m in matches]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("🟢 Bullish",  sentiments.count("bullish"))
            col2.metric("🔴 Bearish",  sentiments.count("bearish"))
            col3.metric("🟡 Neutral",  sentiments.count("neutral"))
            col4.metric("📊 Type",     asset_type.upper())

            score_data = score_ticker(search_ticker, reports)
            if score_data.get("scores_count", 0) > 0:
                st.markdown("---")
                st.subheader(f"🔔 Signal Score — {icon}{search_ticker}")
                sc1, sc2, sc3 = st.columns(3)
                sc1.metric("Score",   f"{score_data['avg_score']:.1f}/10")
                sc2.metric("Signal",  score_data["signal_label"])
                sc3.metric("Reports", score_data["scores_count"])

            memory = get_model_memory(search_ticker)
            if memory.get("total_predictions", 0) > 0:
                st.markdown("---")
                st.subheader(f"🧠 Prediction Memory — {icon}{search_ticker}")
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Predictions",  memory["total_predictions"])
                mc2.metric("Accuracy",     f"{memory['accuracy_pct']}%")
                mc3.metric("Asset Type",   memory.get("asset_type", "stock").upper())
                mc4.metric("Threshold",    memory.get("threshold_used", "±2%"))
                recent = memory.get("recent_outcomes", [])
                if recent:
                    st.dataframe(pd.DataFrame(recent), use_container_width=True)

            if is_commodity or is_etf:
                st.markdown("---")
                sym   = {"GOLD": "GC=F", "SILVER": "SI=F"}.get(search_ticker, search_ticker)
                price, chg = yf_price(sym)
                if price:
                    p1, p2 = st.columns(2)
                    p1.metric(f"{icon} Live Price", f"${price:,}", f"{chg:+.2f}%")

            st.markdown("---")
            for m in matches:
                report     = m["report"]
                t          = m["ticker_data"]
                video      = report.get("video", {})
                price      = report.get("price_data", {}).get(search_ticker, {})
                news       = report.get("news_data",  {}).get(search_ticker, {})
                tech       = report.get("tech_data",  {}).get(search_ticker, {})
                market_ctx = report.get("market_context", {})
                ec = market_ctx.get("earnings_calendar", {}).get(search_ticker, {})
                eh = market_ctx.get("earnings_history",  {}).get(search_ticker, {})
                it = market_ctx.get("insider_trading",   {}).get(search_ticker, {})

                with st.expander(f"📰 {video.get('title', 'Unknown')[:70]}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Source:** {video.get('channel', 'N/A')}")
                        st.markdown(f"**Sentiment:** {sentiment_color(t.get('sentiment'))} {t.get('sentiment', 'N/A').upper()}")
                        st.markdown(f"**Conviction:** {t.get('conviction', 'N/A').upper()}")
                        st.markdown(f"**Context:** {t.get('context', 'N/A')}")
                        if price:
                            st.markdown(f"**Price:** ${price.get('current_price', 'N/A')} ({price.get('change_pct', 'N/A')}%)")
                        if not is_commodity and not is_etf:
                            if ec and "error" not in ec and "status" not in ec:
                                st.markdown(f"**📅 Earnings:** {ec.get('date')} ({ec.get('urgency')})")
                            if eh and "error" not in eh:
                                st.markdown(f"**Beat Rate:** {eh.get('beat_rate')} {'✅' if eh.get('consistent_beater') else '❌'}")
                    with col2:
                        if news:
                            ns = news.get("news_sentiment", {})
                            st.markdown(f"**News:** {ns.get('sentiment', 'N/A').upper()}")
                            st.markdown(f"Bull: {ns.get('bull_score', 0)} | Bear: {ns.get('bear_score', 0)}")
                            for article in news.get("articles", [])[:3]:
                                if "error" not in article:
                                    st.markdown(f"• {article.get('title', '')[:55]}")
                        if is_commodity:
                            st.info(f"{icon} Commodity — no technical indicators")
                        elif is_etf:
                            st.info(f"📦 ETF — see Technical View for indicators")
                        elif tech and "error" not in tech and "skipped" not in tech:
                            st.markdown("---")
                            st.markdown(f"**Tech Signal:** {tech_badge(tech.get('overall_signal'))}")
                            st.markdown(f"**RSI:** {tech.get('rsi', {}).get('value', 'N/A')}")
                            sr = tech.get("support_resistance", {})
                            st.markdown(f"**Support:** ${sr.get('support', 'N/A')} | **Resistance:** ${sr.get('resistance', 'N/A')}")
                        if not is_commodity and not is_etf and it and "error" not in it:
                            st.markdown("---")
                            st.markdown(f"**🏦 Insider:** {it.get('signal')}")
                            st.markdown(f"Last 30d: {it.get('recent_filings_30d', 0)} | Last 90d: {it.get('recent_filings_90d', 0)}")


# ═══════════════════════════════════════════════════════════
# PAGE 4 — TECHNICAL VIEW
# ═══════════════════════════════════════════════════════════
elif page == "📊 Technical View":
    st.title("📊 Technical Indicators View")
    st.markdown("---")

    all_tickers = set()
    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            tk = t.get("ticker")
            if tk and tk.upper() not in {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}:
                all_tickers.add(tk)

    if not all_tickers:
        st.warning("No tickers found yet.")
    else:
        selected = st.selectbox("Select Ticker", sorted(all_tickers))
        if selected:
            is_etf      = selected.upper() in ETF_TICKERS
            latest_tech = None
            for r in reports:
                tech = r.get("tech_data", {}).get(selected)
                if tech and "error" not in tech and "skipped" not in tech:
                    latest_tech = tech
                    break

            if not latest_tech:
                icon = ticker_icon(selected)
                st.warning(f"No technical data for {icon}{selected}")
                if is_etf:
                    price, chg = yf_price(selected)
                    if price:
                        st.metric(f"📦 {selected} Live Price", f"${price:,}", f"{chg:+.2f}%")
                    hist = yf.Ticker(selected).history(period="30d")
                    if not hist.empty:
                        st.line_chart(hist[["Close"]].rename(columns={"Close": selected}))
            else:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("💰 Price",      f"${latest_tech.get('current_price', 'N/A')}")
                col2.metric("📊 Signal",     latest_tech.get("overall_signal", "N/A"))
                col3.metric("🎯 Tech Score", f"{latest_tech.get('technical_score', 'N/A')}/7")
                col4.metric("📈 RSI",        latest_tech.get("rsi", {}).get("value", "N/A"))

                st.markdown("---")
                col_left, col_right = st.columns(2)
                with col_left:
                    st.subheader("📉 MACD")
                    macd = latest_tech.get("macd", {})
                    st.markdown(f"**MACD Line:** `{macd.get('macd_line', 'N/A')}`")
                    st.markdown(f"**Signal Line:** `{macd.get('signal_line', 'N/A')}`")
                    st.markdown(f"**Histogram:** `{macd.get('histogram', 'N/A')}`")
                    crossover = macd.get("crossover", "N/A")
                    st.markdown(f"**Crossover:** {'🟢 BULLISH' if crossover == 'bullish' else '🔴 BEARISH'}")

                    st.subheader("📊 Moving Averages")
                    mas   = latest_tech.get("moving_averages", {})
                    price = latest_tech.get("current_price", 0)
                    for label, key in [("MA 20", "ma_20"), ("MA 50", "ma_50"), ("MA 200", "ma_200")]:
                        val = mas.get(key, "N/A")
                        ind = "🟢 above" if isinstance(val, float) and price > val else "🔴 below"
                        st.markdown(f"**{label}:** ${val} — price is {ind}")

                with col_right:
                    st.subheader("🎯 Support & Resistance")
                    sr = latest_tech.get("support_resistance", {})
                    st.markdown(f"**Support:** ${sr.get('support', 'N/A')} — `{sr.get('pct_to_support', 'N/A')}%` below")
                    st.markdown(f"**Resistance:** ${sr.get('resistance', 'N/A')} — `{sr.get('pct_to_resistance', 'N/A')}%` above")

                    st.subheader("📐 Bollinger Bands")
                    bb = latest_tech.get("bollinger_bands", {})
                    st.markdown(f"**Upper:** ${bb.get('upper_band', 'N/A')}")
                    st.markdown(f"**Lower:** ${bb.get('lower_band', 'N/A')}")
                    st.markdown(f"**Position:** {bb.get('position', 'N/A')}")

                    st.subheader("📦 Volume")
                    vol = latest_tech.get("volume", {})
                    st.markdown(f"**Latest:** {vol.get('latest_volume', 'N/A'):,}" if isinstance(vol.get("latest_volume"), int) else "**Latest:** N/A")
                    st.markdown(f"**20d Avg:** {vol.get('avg_volume_20d', 'N/A'):,}" if isinstance(vol.get("avg_volume_20d"), int) else "**20d Avg:** N/A")
                    st.markdown(f"**Ratio:** {vol.get('volume_ratio', 'N/A')}x | **Signal:** {vol.get('signal', 'N/A')}")

                st.markdown("---")
                trend = latest_tech.get("trend", {})
                st.subheader(f"📈 Trend: {trend.get('trend', 'N/A')}")
                for s in trend.get("signals", []):
                    st.markdown(f"{'✅' if 'above' in s or 'golden' in s else '⚠️'} {s}")

                rsi = latest_tech.get("rsi", {})
                st.info(f"**RSI {rsi.get('value', 'N/A')}** — {rsi.get('interpretation', 'N/A')}")


# ═══════════════════════════════════════════════════════════
# PAGE 5 — MARKET CONTEXT
# ═══════════════════════════════════════════════════════════
elif page == "🌍 Market Context":
    st.title("🌍 Market Context")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        latest_fg = None
        for r in reports:
            fg = r.get("market_context", {}).get("fear_and_greed", {})
            if fg and "error" not in fg:
                latest_fg = fg
                break

        if latest_fg:
            st.subheader("😨 Fear & Greed Index")
            score = latest_fg.get("score", 0)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Score",      f"{score}/100")
            col2.metric("Rating",     str(latest_fg.get("rating", "N/A")).upper())
            col3.metric("Prev Close", latest_fg.get("previous_close", "N/A"))
            col4.metric("1 Week Ago", latest_fg.get("previous_1_week", "N/A"))
            msg = f"**Signal:** {latest_fg.get('signal')}"
            if score <= 25:   st.error(msg)
            elif score <= 45: st.warning(msg)
            elif score <= 55: st.info(msg)
            else:             st.success(msg)
            st.caption(f"💡 {latest_fg.get('interpretation')} | Source: {latest_fg.get('source', 'CNN')}")
        else:
            st.info("No Fear & Greed data found.")

        st.markdown("---")
        st.subheader("📅 Upcoming Earnings")
        earnings_rows = []
        seen_tickers  = set()
        for r in reports:
            for ticker, data in r.get("market_context", {}).get("earnings_calendar", {}).items():
                if ticker not in seen_tickers and "error" not in data and "status" not in data:
                    seen_tickers.add(ticker)
                    earnings_rows.append({
                        "Ticker": ticker, "Date": data.get("date", "N/A"),
                        "Quarter": data.get("quarter", "N/A"), "EPS Est.": data.get("eps_estimate", "N/A"),
                        "Days Until": data.get("days_until", "N/A"), "Urgency": data.get("urgency", "N/A")
                    })
        if earnings_rows:
            st.dataframe(pd.DataFrame(earnings_rows).sort_values("Date"), use_container_width=True)
        else:
            st.info("No upcoming earnings data.")

        st.markdown("---")
        st.subheader("📊 Earnings Beat Rate")
        eh_rows      = []
        seen_tickers = set()
        for r in reports:
            for ticker, data in r.get("market_context", {}).get("earnings_history", {}).items():
                if ticker not in seen_tickers and "error" not in data:
                    seen_tickers.add(ticker)
                    last_4 = data.get("last_4_quarters", [])
                    eh_rows.append({
                        "Ticker": ticker, "Beat Rate": data.get("beat_rate", "N/A"),
                        "Consistent": "✅" if data.get("consistent_beater") else "❌",
                        "Latest EPS": last_4[0].get("actual_eps", "N/A") if last_4 else "N/A",
                        "Surprise %": f"{last_4[0].get('surprise_pct', 'N/A')}%" if last_4 else "N/A",
                        "Result": last_4[0].get("result", "N/A") if last_4 else "N/A"
                    })
        if eh_rows:
            st.dataframe(pd.DataFrame(eh_rows), use_container_width=True)
        else:
            st.info("No earnings history.")

        st.markdown("---")
        st.subheader("🏦 Insider Trading (SEC Form 4)")
        insider_rows = []
        seen_tickers = set()
        for r in reports:
            for ticker, data in r.get("market_context", {}).get("insider_trading", {}).items():
                if ticker not in seen_tickers and "error" not in data:
                    seen_tickers.add(ticker)
                    insider_rows.append({
                        "Ticker": ticker, "Signal": data.get("signal", "N/A"),
                        "Last 30d": data.get("recent_filings_30d", 0),
                        "Last 90d": data.get("recent_filings_90d", 0),
                        "Latest Filing": data.get("latest_filing_date", "N/A")
                    })
        if insider_rows:
            st.dataframe(pd.DataFrame(insider_rows).sort_values("Last 30d", ascending=False), use_container_width=True)
        else:
            st.info("No insider trading data.")


# ═══════════════════════════════════════════════════════════
# PAGE 6 — PREDICTION TRACKER
# ═══════════════════════════════════════════════════════════
elif page == "🧠 Prediction Tracker":
    st.title("🧠 Prediction Tracker")
    st.markdown("---")

    with st.spinner("🔄 Evaluating pending predictions..."):
        evaluate_predictions()

    stats           = get_accuracy_stats()
    all_predictions = load_predictions()

    if not all_predictions:
        st.warning("No predictions logged yet. Run `python feed_watcher.py` to start.")
    else:
        evaluated = [p for p in all_predictions if p["outcome"] in ("correct", "incorrect")]
        pending   = [p for p in all_predictions if p["outcome"] is None]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📊 Total",     len(all_predictions))
        col2.metric("✅ Evaluated", len(evaluated))
        col3.metric("⏳ Pending",   len(pending))
        if stats:
            col4.metric("🎯 Accuracy", f"{stats['accuracy']}%", f"{stats['correct']}/{stats['total']}")

        if stats:
            st.markdown("---")
            ac1, ac2, ac3 = st.columns(3)
            if stats.get("stock_accuracy")     is not None: ac1.metric("📈 Stocks",      f"{stats['stock_accuracy']}%")
            if stats.get("etf_accuracy")       is not None: ac2.metric("📦 ETFs",        f"{stats['etf_accuracy']}%")
            if stats.get("commodity_accuracy") is not None: ac3.metric("🥇 Commodities", f"{stats['commodity_accuracy']}%")

            acc = stats["accuracy"]
            msg = f"Model accuracy: **{acc}%** — {stats['correct']}/{stats['total']} correct"
            if acc >= 70:   st.success(f"🟢 {msg}")
            elif acc >= 50: st.warning(f"🟡 {msg}")
            else:           st.error(f"🔴 {msg}")

        st.markdown("---")

        if stats and stats.get("per_ticker"):
            st.subheader("📊 Accuracy by Ticker")
            ticker_df = pd.DataFrame([
                {
                    "Ticker":     f"{get_asset_icon(t)}{t}",
                    "Accuracy %": s["accuracy"],
                    "Correct":    s["correct"],
                    "Total":      s["total"],
                    "Type":       s.get("asset_type", "stock").upper()
                }
                for t, s in stats["per_ticker"].items()
            ]).sort_values("Accuracy %", ascending=False)
            st.bar_chart(ticker_df.set_index("Ticker")["Accuracy %"])
            st.dataframe(ticker_df, use_container_width=True)

        st.markdown("---")

        if pending:
            st.subheader(f"⏳ Pending ({len(pending)})")
            st.dataframe(pd.DataFrame([
                {
                    "Ticker":         f"{get_asset_icon(p['ticker'])}{p['ticker']}",
                    "Type":           p.get("asset_type", "stock").upper(),
                    "Sentiment":      p["sentiment"].upper(),
                    "Entry $":        f"${p['price_at_prediction']}",
                    "Confidence":     f"{p['confidence'] * 100:.0f}%",
                    "Predicted":      p["predicted_at"][:10],
                    "Evaluate After": p["evaluate_at"][:10],
                    "Source":         p.get("video_title", "")[:50]
                }
                for p in pending
            ]), use_container_width=True)

        st.markdown("---")

        if evaluated:
            st.subheader(f"✅ Evaluated ({len(evaluated)})")
            fc1, fc2, fc3 = st.columns(3)
            with fc1: outcome_filter = st.selectbox("Outcome", ["All", "Correct", "Incorrect"])
            with fc2:
                ticker_options = ["All"] + sorted(set(p["ticker"] for p in evaluated))
                ticker_filter  = st.selectbox("Ticker", ticker_options)
            with fc3: type_filter = st.selectbox("Type", ["All", "Stock", "ETF", "Commodity"])

            filtered = evaluated
            if outcome_filter != "All": filtered = [p for p in filtered if p["outcome"] == outcome_filter.lower()]
            if ticker_filter  != "All": filtered = [p for p in filtered if p["ticker"] == ticker_filter]
            if type_filter    != "All": filtered = [p for p in filtered if p.get("asset_type", "stock") == type_filter.lower()]

            st.dataframe(pd.DataFrame([
                {
                    "Ticker":     f"{get_asset_icon(p['ticker'])}{p['ticker']}",
                    "Type":       p.get("asset_type", "stock").upper(),
                    "Sentiment":  p["sentiment"].upper(),
                    "Outcome":    "✅ Correct" if p["outcome"] == "correct" else "❌ Incorrect",
                    "Entry $":    f"${p['price_at_prediction']}",
                    "Exit $":     f"${p.get('price_at_evaluation', 'N/A')}",
                    "Change %":   f"{p.get('actual_change_pct', 'N/A'):+}%" if isinstance(p.get("actual_change_pct"), float) else "N/A",
                    "Confidence": f"{p['confidence'] * 100:.0f}%",
                    "Predicted":  p["predicted_at"][:10],
                    "Source":     p.get("video_title", "")[:45]
                }
                for p in sorted(filtered, key=lambda x: x["predicted_at"], reverse=True)
            ]), use_container_width=True)

        st.markdown("---")
        if st.button("🔄 Force Re-evaluate All Pending"):
            with st.spinner("Evaluating..."):
                evaluate_predictions()
            st.success("✅ Done!")
            st.rerun()


# ═══════════════════════════════════════════════════════════
# PAGE 7 — COMMODITIES
# ═══════════════════════════════════════════════════════════
elif page == "🥇 Commodities":
    st.title("🥇 Commodities — Gold & Silver")
    st.markdown("---")

    st.subheader("📡 Live Spot Prices")
    col1, col2 = st.columns(2)
    with col1:
        g_price, g_chg = yf_price("GC=F")
        if g_price:
            st.metric("🥇 Gold (GC=F)", f"${g_price:,}", f"{g_chg:+.2f}%")
            hist = yf.Ticker("GC=F").history(period="5d")
            if not hist.empty:
                st.line_chart(hist[["Close"]].rename(columns={"Close": "Gold Price"}))
    with col2:
        s_price, s_chg = yf_price("SI=F")
        if s_price:
            st.metric("🥈 Silver (SI=F)", f"${s_price:,}", f"{s_chg:+.2f}%")
            hist = yf.Ticker("SI=F").history(period="5d")
            if not hist.empty:
                st.line_chart(hist[["Close"]].rename(columns={"Close": "Silver Price"}))

    if g_price and s_price:
        ratio = round(g_price / s_price, 2)
        st.markdown("---")
        st.subheader("⚖️ Gold/Silver Ratio")
        r1, r2 = st.columns(2)
        r1.metric("Current Ratio", f"{ratio}:1")
        if   ratio > 80: r2.warning(f"🔼 High ({ratio}) — silver undervalued vs gold")
        elif ratio < 60: r2.success(f"🔽 Low ({ratio}) — silver expensive vs gold")
        else:            r2.info(f"➡️ Neutral ({ratio})")

    st.markdown("---")
    st.subheader("📊 Related ETFs")
    ec1, ec2, ec3 = st.columns(3)
    for col, sym, label in [(ec1, "GLD", "🥇 GLD"), (ec2, "SLV", "🥈 SLV"), (ec3, "SVR.TO", "🥈 SVR.TO")]:
        p, c = yf_price(sym)
        col.metric(label, f"${p}" if p else "N/A", f"{c:+.2f}%" if c is not None else "")

    st.markdown("---")
    st.subheader("📰 Commodity Sentiment from Reports")
    commodity_rows = []
    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            tk = t.get("ticker", "")
            if tk.upper() in COMMODITY_KEYWORDS:
                pd_ = r.get("price_data", {}).get(tk, {})
                commodity_rows.append({
                    "Ticker":     f"{ticker_icon(tk)}{tk}",
                    "Sentiment":  t.get("sentiment", "N/A").upper(),
                    "Conviction": t.get("conviction", "N/A").upper(),
                    "Price":      f"${pd_.get('current_price', 'N/A')}",
                    "Change %":   f"{pd_.get('change_pct', 'N/A')}%",
                    "Context":    t.get("context", "")[:80],
                    "Source":     r.get("video", {}).get("channel", "N/A"),
                    "Date":       r.get("analyzed_at", "N/A")[:10]
                })
    if commodity_rows:
        st.dataframe(pd.DataFrame(commodity_rows), use_container_width=True)
    else:
        st.info("No commodity mentions in reports yet.")

    st.markdown("---")
    st.subheader("🧠 Commodity Predictions")
    c_preds = [p for p in load_predictions() if p.get("asset_type") == "commodity"]
    if not c_preds:
        st.info("No commodity predictions yet.")
    else:
        st.dataframe(pd.DataFrame([
            {
                "Ticker":    f"{get_asset_icon(p['ticker'])}{p['ticker']}",
                "Sentiment": p["sentiment"].upper(),
                "Outcome":   "✅" if p["outcome"] == "correct" else ("❌" if p["outcome"] == "incorrect" else "⏳"),
                "Entry $":   f"${p['price_at_prediction']}",
                "Change %":  f"{p.get('actual_change_pct', 'N/A'):+}%" if isinstance(p.get("actual_change_pct"), float) else "Pending",
                "Date":      p["predicted_at"][:10],
                "Source":    p.get("video_title", "")[:50]
            }
            for p in sorted(c_preds, key=lambda x: x["predicted_at"], reverse=True)
        ]), use_container_width=True)

        ev = [p for p in c_preds if p["outcome"] in ("correct", "incorrect")]
        if ev:
            acc = round(sum(1 for p in ev if p["outcome"] == "correct") / len(ev) * 100, 1)
            msg = f"🥇 Commodity accuracy: **{acc}%** ({len(ev)} evaluated)"
            if acc >= 70:   st.success(msg)
            elif acc >= 50: st.warning(msg)
            else:           st.error(msg)


# ═══════════════════════════════════════════════════════════
# PAGE 8 — ETFs
# ═══════════════════════════════════════════════════════════
elif page == "📦 ETFs":
    st.title("📦 ETF Tracker")
    st.markdown("Live prices, sentiment history, and predictions for ETFs.")
    st.markdown("---")

    st.subheader("⭐ Your ETF Watchlist")
    cols = st.columns(len(YOUR_ETFS))
    for col, sym in zip(cols, YOUR_ETFS):
        price, chg = yf_price(sym)
        col.metric(f"📦 {sym}", f"${price:,}" if price else "N/A", f"{chg:+.2f}%" if chg is not None else "")

    st.markdown("---")
    st.subheader("🌍 Broad Market")
    mc = st.columns(len(MARKET_ETFS))
    for col, (sym, label) in zip(mc, MARKET_ETFS.items()):
        price, chg = yf_price(sym)
        col.metric(label, f"${price:,}" if price else "N/A", f"{chg:+.2f}%" if chg is not None else "")

    st.markdown("---")
    st.subheader("🏭 Sector ETFs")
    sc = st.columns(4)
    for i, (sym, label) in enumerate(SECTOR_ETFS.items()):
        price, chg = yf_price(sym)
        sc[i % 4].metric(f"{label} ({sym})", f"${price:,}" if price else "N/A", f"{chg:+.2f}%" if chg is not None else "")

    st.markdown("---")
    st.subheader("📈 30-Day Price Chart")
    all_etf_opts = sorted(set(YOUR_ETFS) | set(SECTOR_ETFS.keys()) | set(MARKET_ETFS.keys()))
    selected_etf = st.selectbox("Select ETF", all_etf_opts)
    try:
        hist = yf.Ticker(selected_etf).history(period="30d")
        if not hist.empty:
            st.line_chart(hist[["Close"]].rename(columns={"Close": f"{selected_etf} Price"}))
    except Exception:
        st.warning(f"Could not fetch chart for {selected_etf}")

    st.markdown("---")
    st.subheader("📰 ETF Sentiment from Reports")
    etf_rows = []
    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            tk = t.get("ticker", "")
            if tk.upper() in ETF_TICKERS:
                pd_ = r.get("price_data", {}).get(tk, {})
                etf_rows.append({
                    "Ticker":     f"📦 {tk}",
                    "Sentiment":  t.get("sentiment", "N/A").upper(),
                    "Conviction": t.get("conviction", "N/A").upper(),
                    "Price":      f"${pd_.get('current_price', 'N/A')}",
                    "Change %":   f"{pd_.get('change_pct', 'N/A')}%",
                    "Context":    t.get("context", "")[:80],
                    "Source":     r.get("video", {}).get("channel", "N/A"),
                    "Date":       r.get("analyzed_at", "N/A")[:10]
                })

    if etf_rows:
        st.dataframe(pd.DataFrame(etf_rows), use_container_width=True)
        st.markdown("---")
        st.subheader("📊 ETF Sentiment Summary")
        etf_counts = {}
        for row in etf_rows:
            tk = row["Ticker"].replace("📦 ", "")
            if tk not in etf_counts:
                etf_counts[tk] = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
            etf_counts[tk][row["Sentiment"]] = etf_counts[tk].get(row["Sentiment"], 0) + 1
        for tk, counts in sorted(etf_counts.items()):
            st.markdown(
                f"**📦 {tk}** — "
                f"🟢 {counts.get('BULLISH', 0)} Bullish | "
                f"🔴 {counts.get('BEARISH', 0)} Bearish | "
                f"🟡 {counts.get('NEUTRAL', 0)} Neutral"
            )
    else:
        st.info("No ETF mentions in reports yet.")

    st.markdown("---")
    st.subheader("🧠 ETF Predictions")
    e_preds = [p for p in load_predictions() if p.get("asset_type") == "etf"]
    if not e_preds:
        st.info("No ETF predictions yet.")
    else:
        st.dataframe(pd.DataFrame([
            {
                "Ticker":     f"📦 {p['ticker']}",
                "Sentiment":  p["sentiment"].upper(),
                "Outcome":    "✅" if p["outcome"] == "correct" else ("❌" if p["outcome"] == "incorrect" else "⏳"),
                "Entry $":    f"${p['price_at_prediction']}",
                "Change %":   f"{p.get('actual_change_pct', 'N/A'):+}%" if isinstance(p.get("actual_change_pct"), float) else "Pending",
                "Confidence": f"{p['confidence'] * 100:.0f}%",
                "Date":       p["predicted_at"][:10],
                "Source":     p.get("video_title", "")[:50]
            }
            for p in sorted(e_preds, key=lambda x: x["predicted_at"], reverse=True)
        ]), use_container_width=True)

        ev = [p for p in e_preds if p["outcome"] in ("correct", "incorrect")]
        if ev:
            acc = round(sum(1 for p in ev if p["outcome"] == "correct") / len(ev) * 100, 1)
            msg = f"📦 ETF accuracy: **{acc}%** ({len(ev)} evaluated)"
            if acc >= 70:   st.success(msg)
            elif acc >= 50: st.warning(msg)
            else:           st.error(msg)


# ═══════════════════════════════════════════════════════════
# PAGE 9 — SIGNAL SCORES
# ═══════════════════════════════════════════════════════════
elif page == "🔔 Signal Scores":
    st.title("🔔 Signal Strength Scores")
    st.markdown("Combined score (0–10) based on sentiment, news, technicals, RSI, MACD, conviction, confidence, and insider activity.")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        with st.spinner("Calculating scores..."):
            all_scores = score_all_tickers(reports)

        if not all_scores:
            st.info("No ticker scores available yet.")
        else:
            st.subheader("🏆 Top 5 Signals")
            top5 = list(all_scores.items())[:5]
            cols = st.columns(5)
            for col, (ticker, data) in zip(cols, top5):
                score = data["avg_score"]
                label = data["signal_label"]
                icon  = ticker_icon(ticker)
                col.metric(f"{icon}{ticker}", f"{score:.1f}/10", label)

            st.markdown("---")
            st.subheader("📊 All Ticker Scores")
            score_rows = []
            for ticker, data in all_scores.items():
                bd    = data.get("breakdown", {})
                score = data["avg_score"]
                color = "🟢" if score >= 7 else "🔴" if score <= 3 else "🟡"
                score_rows.append({
                    "Ticker":     f"{ticker_icon(ticker)}{ticker}",
                    "Score":      f"{color} {score:.1f}/10",
                    "Signal":     data["signal_label"],
                    "Sentiment":  f"{bd.get('sentiment', 0):.1f}",
                    "News":       f"{bd.get('news', 0):.1f}",
                    "Tech":       f"{bd.get('tech', 0):.1f}",
                    "RSI":        f"{bd.get('rsi', 0):.1f}",
                    "MACD":       f"{bd.get('macd', 0):.1f}",
                    "Conviction": f"{bd.get('conviction', 0):.1f}",
                    "Confidence": f"{bd.get('confidence', 0):.1f}",
                    "Insider":    f"{bd.get('insider', 0):.1f}",
                    "Reports":    data["scores_count"]
                })
            st.dataframe(pd.DataFrame(score_rows), use_container_width=True)

            st.markdown("---")
            st.subheader("📈 Score Chart")
            chart_data = pd.DataFrame([
                {"Ticker": f"{ticker_icon(t)}{t}", "Score": d["avg_score"]}
                for t, d in all_scores.items()
            ]).sort_values("Score", ascending=False).head(15).set_index("Ticker")
            st.bar_chart(chart_data)

            st.markdown("---")
            st.subheader("🔎 Deep Dive")
            selected = st.selectbox("Select Ticker", list(all_scores.keys()))
            if selected:
                data = all_scores[selected]
                bd   = data.get("breakdown", {})
                st.markdown(f"### {ticker_icon(selected)}{selected} — {data['signal_label']} ({data['avg_score']:.1f}/10)")
                d1, d2, d3, d4, d5, d6, d7, d8 = st.columns(8)
                d1.metric("Sentiment",  f"{bd.get('sentiment', 0):.1f}/2")
                d2.metric("News",       f"{bd.get('news', 0):.1f}/1")
                d3.metric("Tech",       f"{bd.get('tech', 0):.1f}/2")
                d4.metric("RSI",        f"{bd.get('rsi', 0):.1f}/1")
                d5.metric("MACD",       f"{bd.get('macd', 0):.1f}/1")
                d6.metric("Conviction", f"{bd.get('conviction', 0):.1f}/1")
                d7.metric("Confidence", f"{bd.get('confidence', 0):.1f}/1")
                d8.metric("Insider",    f"{bd.get('insider', 0):.1f}/1")
                for s in data.get("scores", []):
                    st.caption(f"📰 {s['source']} [{s['date']}] → {s['total_score']:.1f}/10")


# ═══════════════════════════════════════════════════════════
# PAGE 10 — AUTO WATCHLIST
# ═══════════════════════════════════════════════════════════
elif page == "🔥 Auto Watchlist":
    st.title("🔥 Auto-Learned Watchlist")
    st.markdown("Tickers automatically ranked by mention frequency, conviction, source diversity, and recency.")
    st.markdown("---")

    col1, col2 = st.columns([3, 1])
    with col1:
        days_back = st.slider("Look back (days)", 7, 90, 30)
    with col2:
        min_mentions = st.number_input("Min mentions", 1, 10, 2)

    if st.button("🔄 Refresh & Save Watchlist"):
        save_watchlist(reports)
        st.success("✅ Watchlist updated!")

    with st.spinner("Learning from reports..."):
        top_tickers = get_top_tickers(reports, top_n=30, min_mentions=int(min_mentions))

    if not top_tickers:
        st.info("Not enough data yet. Run `feed_watcher.py` to collect more reports.")
    else:
        st.subheader("🏆 Most Followed")
        cols = st.columns(6)
        for col, entry in zip(cols, top_tickers[:6]):
            icon     = ticker_icon(entry["ticker"])
            bull_pct = entry["bull_pct"]
            delta    = f"🟢 {bull_pct:.0f}% bull" if bull_pct >= 60 else f"🔴 {bull_pct:.0f}% bull" if bull_pct <= 40 else f"🟡 {bull_pct:.0f}% bull"
            col.metric(f"{icon}{entry['ticker']}", f"{entry['count']} mentions", delta)

        st.markdown("---")
        stocks      = [e for e in top_tickers if e["asset_type"] == "stock"]
        etfs        = [e for e in top_tickers if e["asset_type"] == "etf"]
        commodities = [e for e in top_tickers if e["asset_type"] == "commodity"]

        tab1, tab2, tab3 = st.tabs(["📈 Stocks", "📦 ETFs", "🥇 Commodities"])

        def render_watchlist_table(entries):
            if not entries:
                st.info("None in this category.")
                return
            rows = []
            for e in entries:
                bull_pct = e["bull_pct"]
                bias     = "🟢 Bullish" if bull_pct >= 60 else "🔴 Bearish" if bull_pct <= 40 else "🟡 Mixed"
                rows.append({
                    "Ticker":    f"{ticker_icon(e['ticker'])}{e['ticker']}",
                    "Mentions":  e["count"],
                    "Bias":      bias,
                    "Bull %":    f"{bull_pct:.0f}%",
                    "Hi-Conv":   e["high_conviction"],
                    "Sources":   e["source_count"],
                    "Score":     f"{e['score']:.1f}",
                    "Last Seen": e["last_seen"],
                    "Context":   e["contexts"][0][:60] if e["contexts"] else ""
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        with tab1: render_watchlist_table(stocks)
        with tab2: render_watchlist_table(etfs)
        with tab3: render_watchlist_table(commodities)

        st.markdown("---")
        st.subheader("📊 Mention Volume")
        chart_df = pd.DataFrame([
            {"Ticker": f"{ticker_icon(e['ticker'])}{e['ticker']}", "Mentions": e["count"]}
            for e in top_tickers[:20]
        ]).set_index("Ticker")
        st.bar_chart(chart_df)


# ═══════════════════════════════════════════════════════════
# PAGE 11 — CONTRADICTIONS
# ═══════════════════════════════════════════════════════════
elif page == "⚠️ Contradictions":
    st.title("⚠️ Contradiction Detector")
    st.markdown("Tickers where bullish and bearish signals conflict across sources.")
    st.markdown("---")

    days_back = st.slider("Look back (days)", 3, 30, 7)

    with st.spinner("Analyzing signals..."):
        contradictions = detect_contradictions(reports, days=days_back)

    if not contradictions:
        st.success(f"✅ No conflicting signals in the last {days_back} days!")
    else:
        st.warning(f"⚠️ Found **{len(contradictions)}** ticker(s) with conflicting signals")
        st.markdown("---")

        for ticker, data in contradictions.items():
            level = data["conflict_level"]
            score = data["conflict_score"]
            color = "🔴" if level == "HIGH" else "🟡" if level == "MEDIUM" else "🟠"

            with st.expander(
                f"{color} **{ticker}** — Conflict: {level} ({score}/10) | 🟢 {data['bullish']} Bull vs 🔴 {data['bearish']} Bear",
                expanded=(level == "HIGH")
            ):
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("🟢 Bullish",    data["bullish"])
                col2.metric("🔴 Bearish",    data["bearish"])
                col3.metric("Total Signals", data["total"])
                col4.metric("Conflict",      f"{score}/10")
                col5.metric("Dominant",      data["dominant"])

                dom = data["dominant"]
                if dom == "BULLISH":
                    st.success(f"💡 {data['recommendation']}")
                elif dom == "BEARISH":
                    st.error(f"💡 {data['recommendation']}")
                else:
                    st.warning(f"💡 {data['recommendation']}")

                col_b, col_r = st.columns(2)
                with col_b:
                    st.markdown("**🟢 Bullish Arguments:**")
                    for ctx in data.get("bullish_contexts", []):
                        st.markdown(f"• {ctx}")
                    st.caption("Sources: " + ", ".join(set(data.get("bullish_sources", [])))[:80])
                with col_r:
                    st.markdown("**🔴 Bearish Arguments:**")
                    for ctx in data.get("bearish_contexts", []):
                        st.markdown(f"• {ctx}")
                    st.caption("Sources: " + ", ".join(set(data.get("bearish_sources", [])))[:80])

        st.markdown("---")
        st.subheader("📊 Conflict Overview")
        cf_df = pd.DataFrame([
            {
                "Ticker":   f"{ticker_icon(t)}{t}",
                "Bullish":  d["bullish"],
                "Bearish":  d["bearish"],
                "Score":    d["conflict_score"],
                "Level":    d["conflict_level"],
                "Dominant": d["dominant"]
            }
            for t, d in contradictions.items()
        ]).sort_values("Score", ascending=False)
        st.dataframe(cf_df, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# PAGE 12 — DAILY DIGEST
# ═══════════════════════════════════════════════════════════
elif page == "📧 Daily Digest":
    st.title("📧 Daily Digest")
    st.markdown("Preview and send your market briefing email.")
    st.markdown("---")

    from daily_digest import build_digest_html, send_digest_email, load_recent_reports
    import streamlit.components.v1 as components

    hours = st.slider("Digest covers last N hours", 6, 72, 24)
    reports_24h = load_recent_reports(hours=hours)
    st.info(f"📊 **{len(reports_24h)}** reports from the last {hours}h will be included.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("👁️ Preview Digest", type="primary"):
            with st.spinner("Building digest..."):
                html = build_digest_html(reports_24h, reports)
            st.markdown("### Preview:")
            components.html(html, height=800, scrolling=True)
    with col2:
        if st.button("📧 Send Now"):
            to_email = os.getenv("DIGEST_EMAIL_TO")
            if not to_email:
                st.error("Set DIGEST_EMAIL_TO in your .env file first.")
            else:
                with st.spinner("Sending..."):
                    html = build_digest_html(reports_24h, reports)
                    send_digest_email(html)
                st.success(f"✅ Sent to {to_email}!")

    st.markdown("---")
    st.subheader("⚙️ Email Setup")
    st.markdown("""
Add these to your `.env`:
**Get Gmail App Password:**
1. Google Account → Security → 2-Step Verification → App Passwords
2. Create app password for "Mail"
3. Paste the 16-character password above
    """)

    st.subheader("⏰ Auto Schedule")
    st.markdown("""
Run in a separate terminal:
```bash
python daily_digest.py         # sends at 8:00 AM daily
python daily_digest.py now     # send immediately
```""")


# ═══════════════════════════════════════════════════════════
# PAGE 13 — ANALYZE VIDEO
# ═══════════════════════════════════════════════════════════
elif page == "▶️ Analyze Video":
    st.title("▶️ Analyze a YouTube Video")
    st.markdown("Paste any YouTube URL to analyze it instantly.")
    st.markdown("---")
    video_url = st.text_input("YouTube URL or Video ID", placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX")

    if st.button("🚀 Analyze Now", type="primary"):
        if not video_url:
            st.error("Please enter a YouTube URL or video ID")
        else:
            if "watch?v=" in video_url:
                video_id = video_url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]
            else:
                video_id = video_url.strip()

            from watcher import (
                get_transcript, analyze_with_claude,
                get_price_data, get_sec_data,
                COMMODITY_KEYWORDS, SKIP_TECHNICALS, ETF_TICKERS
            )
            from news_collector import get_ticker_news_with_sentiment
            from technical_indicators import get_technical_indicators
            from market_context import get_market_context

            with st.spinner("📥 Fetching transcript..."):
                transcript = get_transcript(video_id)

            if not transcript:
                st.error("❌ Could not fetch transcript.")
            else:
                st.success(f"✅ Transcript fetched! ({len(transcript):,} chars)")

                with st.spinner("🤖 First pass..."):
                    first_pass = analyze_with_claude(transcript)

                price_map, sec_map, news_map, tech_map, memory_map = {}, {}, {}, {}, {}

                with st.spinner("📡 Fetching market data..."):
                    for t in first_pass.get("tickers", []):
                        ticker       = t.get("ticker")
                        is_commodity = ticker.upper() in COMMODITY_KEYWORDS
                        is_etf       = ticker.upper() in ETF_TICKERS
                        price_map[ticker]  = get_price_data(ticker)
                        sec_map[ticker]    = get_sec_data(ticker)
                        news_map[ticker]   = get_ticker_news_with_sentiment(ticker, t.get("company", ""))
                        memory_map[ticker] = get_model_memory(ticker)
                        if is_commodity or ticker.upper() in SKIP_TECHNICALS:
                            tech_map[ticker] = {"skipped": "Commodity"}
                        else:
                            tech_map[ticker] = get_technical_indicators(ticker)

                with st.spinner("🤖 Re-analyzing with full context..."):
                    analysis = analyze_with_claude(
                        transcript,
                        price_map=price_map,
                        news_map=news_map,
                        tech_map=tech_map,
                        memory_map=memory_map
                    )

                tickers    = [t.get("ticker") for t in analysis.get("tickers", [])]
                stock_only = [t for t in tickers if t.upper() not in COMMODITY_KEYWORDS and t.upper() not in ETF_TICKERS]

                with st.spinner("🌍 Fetching market context..."):
                    market_ctx = get_market_context(stock_only)

                st.success("✅ Done!")
                st.markdown("---")

                sentiment  = analysis.get("overall_market_sentiment", "neutral")
                confidence = analysis.get("confidence_score", 0) * 100

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📈 Sentiment",     sentiment.upper())
                col2.metric("🎯 Confidence",    f"{confidence:.0f}%")
                col3.metric("📌 Tickers Found", len(analysis.get("tickers", [])))
                commodity_count = sum(1 for t in analysis.get("tickers", []) if t.get("ticker", "").upper() in COMMODITY_KEYWORDS)
                col4.metric("🥇 Commodities",   commodity_count)

                fg = market_ctx.get("fear_and_greed", {})
                if fg and "error" not in fg:
                    st.info(f"😨 **Fear & Greed:** {fg.get('score')}/100 — {fg.get('signal')}")

                st.markdown("---")
                for t in analysis.get("tickers", []):
                    ticker       = t.get("ticker")
                    is_commodity = ticker.upper() in COMMODITY_KEYWORDS
                    is_etf       = ticker.upper() in ETF_TICKERS
                    icon         = ticker_icon(ticker)
                    price        = price_map.get(ticker, {})
                    news         = news_map.get(ticker, {})
                    tech         = tech_map.get(ticker, {})
                    ns           = news.get("news_sentiment", {})
                    ec           = market_ctx.get("earnings_calendar", {}).get(ticker, {})
                    eh           = market_ctx.get("earnings_history",  {}).get(ticker, {})
                    it           = market_ctx.get("insider_trading",   {}).get(ticker, {})
                    mem          = memory_map.get(ticker, {})

                    with st.expander(f"`{icon}{ticker}` — {t.get('company')} — {sentiment_color(t.get('sentiment'))} {t.get('sentiment', '').upper()} | Conviction: {t.get('conviction', 'N/A').upper()}"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.markdown("**📈 Price & Context**")
                            st.markdown(f"Price: ${price.get('current_price', 'N/A')}")
                            st.markdown(f"Change: {price.get('change_pct', 'N/A')}%")
                            st.markdown(f"Type: {get_asset_type(ticker).upper()}")
                            st.markdown(f"Context: {t.get('context', 'N/A')}")
                            if not is_commodity and not is_etf:
                                if ec and "error" not in ec and "status" not in ec:
                                    st.markdown(f"**📅 Earnings:** {ec.get('date')} ({ec.get('urgency')})")
                                if eh and "error" not in eh:
                                    st.markdown(f"**Beat Rate:** {eh.get('beat_rate')} {'✅' if eh.get('consistent_beater') else '❌'}")
                            if mem.get("total_predictions", 0) > 0:
                                st.markdown("---")
                                st.markdown(f"**🧠 Past Accuracy:** {mem.get('accuracy_pct')}% ({mem.get('total_predictions')} preds)")
                                st.caption(f"Threshold: {mem.get('threshold_used', '±2%')}")
                        with col2:
                            st.markdown("**📰 News**")
                            if ns:
                                st.markdown(f"Sentiment: {ns.get('sentiment', 'N/A').upper()}")
                                st.markdown(f"Bull: {ns.get('bull_score', 0)} | Bear: {ns.get('bear_score', 0)}")
                            for article in news.get("articles", [])[:3]:
                                if "error" not in article:
                                    st.markdown(f"• {article.get('title', '')[:55]}")
                            if not is_commodity and not is_etf and it and "error" not in it:
                                st.markdown("---")
                                st.markdown(f"**🏦 Insider:** {it.get('signal')}")
                        with col3:
                            if is_commodity:
                                st.info(f"{icon} Commodity — no technicals")
                            elif is_etf:
                                st.info(f"📦 ETF — see ETFs page")
                                p, c = yf_price(ticker)
                                if p:
                                    st.metric("Live Price", f"${p:,}", f"{c:+.2f}%")
                            elif tech and "error" not in tech and "skipped" not in tech:
                                st.markdown("**📊 Technicals**")
                                st.markdown(f"Signal: {tech_badge(tech.get('overall_signal'))}")
                                st.markdown(f"RSI: {tech.get('rsi', {}).get('value', 'N/A')}")
                                st.markdown(f"MACD: {tech.get('macd', {}).get('crossover', 'N/A').upper()}")
                                st.markdown(f"Trend: {tech.get('trend', {}).get('trend', 'N/A')}")
                                sr = tech.get("support_resistance", {})
                                st.markdown(f"Support: ${sr.get('support', 'N/A')} | Res: ${sr.get('resistance', 'N/A')}")

                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("🟢 Bull Cases")
                    for b in analysis.get("bull_cases", []):
                        st.markdown(f"• {b}")
                with col2:
                    st.subheader("🔴 Bear Cases")
                    for b in analysis.get("bear_cases", []):
                        st.markdown(f"• {b}")

                st.subheader("💡 Investment Tactics")
                for tac in analysis.get("investment_tactics", []):
                    st.markdown(f"• {tac}")

                if confidence >= 50:
                    for t in analysis.get("tickers", []):
                        ticker      = t.get("ticker")
                        entry_price = price_map.get(ticker, {}).get("current_price", 0)
                        log_prediction(
                            ticker=ticker,
                            sentiment=t.get("sentiment", "neutral"),
                            price_at_prediction=entry_price,
                            confidence=analysis.get("confidence_score", 0),
                            video_id=video_id,
                            video_title=f"Manual: {video_id}"
                        )
                    st.info("📝 Predictions logged to tracker.")

                # ✅ Save to DB via save_report()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_obj = {
                    "video_id":     video_id,
                    "title":        "Manual Analysis",
                    "channel":      "Manual",
                    "published_at": timestamp
                }
                from watcher import save_report
                save_report(video_obj, analysis, price_map, sec_map, news_map, tech_map, market_ctx)
                st.cache_data.clear()
                st.success(f"💾 Saved to DB + JSON ✅")


# ═══════════════════════════════════════════════════════════
# PAGE — SECTOR ROTATION HEATMAP
# ═══════════════════════════════════════════════════════════
elif page == "🌡️ Sector Rotation":
    st.title("🌡️ Sector Rotation Heatmap")
    st.markdown("*Which sectors are gaining or losing bullish sentiment week over week*")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        try:
            from sector_rotation import build_rotation_data, get_sector_summary
            import pandas as pd

            weeks = st.slider("Weeks to show", 2, 8, 5)
            days_summary = st.slider("Summary: last N days", 3, 30, 7)

            with st.spinner("Building heatmap..."):
                rotation_data, week_labels = build_rotation_data(reports, weeks=weeks)
                summary = get_sector_summary(reports, days=days_summary)

            if not rotation_data:
                st.info("Not enough data across multiple weeks yet. Keep collecting reports!")
            else:
                st.subheader("📊 Weekly Sentiment Score by Sector")
                st.caption("Score: +1.0 = all bullish, -1.0 = all bearish, 0 = neutral")

                all_sectors = sorted(rotation_data.keys())
                heatmap_rows = []
                for sector in all_sectors:
                    row = {"Sector": sector}
                    for label in week_labels[-weeks:]:
                        score = rotation_data[sector].get(label, None)
                        row[label] = score
                    heatmap_rows.append(row)

                hdf = pd.DataFrame(heatmap_rows).set_index("Sector").fillna(0)

                def color_score(val):
                    if val > 0.3:   return "background-color: #1a4d2e; color: #00ff88"
                    if val > 0:     return "background-color: #1a3d1e; color: #88ffaa"
                    if val < -0.3:  return "background-color: #4d1a1a; color: #ff8888"
                    if val < 0:     return "background-color: #3d1a1a; color: #ffaaaa"
                    return "background-color: #2a2a2a; color: #aaaaaa"

                styled = hdf.style.applymap(color_score).format("{:+.2f}")
                st.dataframe(styled, use_container_width=True)

                st.markdown("---")
                st.subheader(f"🏆 Sector Rankings — Last {days_summary} Days")

                if summary:
                    col1, col2, col3 = st.columns(3)
                    top3    = summary[:3]
                    bottom3 = summary[-3:]

                    with col1:
                        st.markdown("**🟢 Top Sectors**")
                        for s in top3:
                            st.metric(s["sector"], f"{s['score']:+.1f}/10",
                                      f"{s['bull']}🟢 {s['bear']}🔴")

                    with col2:
                        st.markdown("**🔴 Weakest Sectors**")
                        for s in bottom3:
                            st.metric(s["sector"], f"{s['score']:+.1f}/10",
                                      f"{s['bull']}🟢 {s['bear']}🔴")

                    with col3:
                        st.markdown("**📊 All Sectors**")
                        for s in summary:
                            color = "🟢" if s["score"] > 2 else "🔴" if s["score"] < -2 else "🟡"
                            st.markdown(f"{color} **{s['sector']}** `{s['score']:+.1f}`")

                    st.markdown("---")
                    st.subheader("📋 Full Sector Detail")
                    sector_df = pd.DataFrame([{
                        "Sector":  s["sector"],
                        "Score":   f"{s['score']:+.1f}",
                        "Bias":    s["bias"],
                        "🟢 Bull": s["bull"],
                        "🔴 Bear": s["bear"],
                        "Total":   s["total"],
                        "Tickers": ", ".join(s["tickers"][:6])
                    } for s in summary])
                    st.dataframe(sector_df, use_container_width=True)

        except ImportError:
            st.error("❌ Missing `sector_rotation.py` — make sure it's in your project folder.")


# ═══════════════════════════════════════════════════════════
# PAGE — TREND DETECTION
# ═══════════════════════════════════════════════════════════
elif page == "📈 Trend Detection":
    st.title("📈 Trend Detection — Breakout Attention")
    st.markdown("*Tickers suddenly getting more mentions than usual*")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        try:
            from trend_detector import detect_trending_tickers

            c1, c2, c3 = st.columns(3)
            with c1: recent_days   = st.slider("Recent window (days)",   3, 14, 7)
            with c2: baseline_days = st.slider("Baseline window (days)", 7, 60, 21)
            with c3: min_mentions  = st.slider("Min recent mentions",    1, 10,  2)

            with st.spinner("Detecting trends..."):
                trends = detect_trending_tickers(
                    reports=reports,
                    window_recent=recent_days,
                    window_baseline=baseline_days,
                    min_recent=min_mentions
                )

            if not trends:
                st.success("✅ No breakout tickers detected in this window.")
            else:
                st.success(f"🔥 Found **{len(trends)}** trending tickers!")

                top6 = trends[:6]
                cols = st.columns(len(top6))
                for col, t in zip(cols, top6):
                    col.metric(
                        f"{t['alert']} {t['ticker']}",
                        f"{t['breakout_score']}x",
                        f"{t['recent_count']} mentions"
                    )

                st.markdown("---")

                alert_filter = st.selectbox("Filter by alert type",
                    ["All", "🆕 NEW", "🔥 HOT", "📈 RISING", "👀 WATCH"])

                filtered = trends if alert_filter == "All" else [
                    t for t in trends if t["alert"] == alert_filter
                ]

                for t in filtered:
                    with st.expander(
                        f"{t['alert']} **{t['ticker']}** — "
                        f"{t['breakout_score']}x breakout | {t['bias']}",
                        expanded=(t["alert"] in ("🆕 NEW", "🔥 HOT"))
                    ):
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Recent Mentions",   t["recent_count"])
                        col2.metric("Baseline Mentions", t["baseline_count"])
                        col3.metric("Breakout Score",    f"{t['breakout_score']}x")
                        col4.metric("Bull %",            f"{t['bull_pct']}%")

                        st.markdown(f"**Bias:** {t['bias']}")
                        st.markdown(f"**Sources ({t['source_count']}):** {', '.join(t['sources'][:5])}")
                        if t["contexts"]:
                            st.markdown("**Context:**")
                            for ctx in t["contexts"]:
                                st.caption(f"• {ctx}")

                st.markdown("---")
                st.subheader("📊 Breakout Scores Overview")
                chart_df = pd.DataFrame([{
                    "Ticker": f"{t['alert']} {t['ticker']}",
                    "Breakout": t["breakout_score"]
                } for t in trends[:20]]).set_index("Ticker")
                st.bar_chart(chart_df)

        except ImportError:
            st.error("❌ Missing `trend_detector.py` — make sure it's in your project folder.")


# ═══════════════════════════════════════════════════════════
# PAGE — BACKTEST
# ═══════════════════════════════════════════════════════════
elif page == "🔁 Backtest":
    st.title("🔁 Signal Backtest")
    st.markdown("*How well did past bullish/bearish signals perform at different hold periods?*")
    st.markdown("---")

    if not reports:
        st.warning("No reports found yet.")
    else:
        try:
            from backtester import run_backtest, get_backtest_summary

            c1, c2 = st.columns(2)
            with c1:
                min_conf = st.slider("Min confidence %", 0, 90, 50) / 100
            with c2:
                hold_days = st.selectbox("Hold period (days)", [3, 7, 14, 30], index=1)

            with st.spinner("⏳ Fetching historical prices & running backtest..."):
                trades  = run_backtest(reports=reports, min_confidence=min_conf)
                summary = get_backtest_summary(trades, hold_days=hold_days)

            if not trades:
                st.warning("Not enough signals to backtest yet.")
            else:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📊 Total Trades",  summary["total_trades"])
                col2.metric("🎯 Win Rate",      f"{summary['win_rate']}%")
                col3.metric("📈 Avg Return",    f"{summary['avg_return']:+.2f}%")

                wc = summary["wins"]
                lc = summary["losses"]
                fc = summary["flat"]
                color_fn = st.success if summary["win_rate"] >= 60 else (
                           st.warning if summary["win_rate"] >= 45 else st.error)
                color_fn(
                    f"**{hold_days}-Day Hold:** {summary['win_rate']}% win rate | "
                    f"✅ {wc} wins | ❌ {lc} losses | ➡️ {fc} flat"
                )

                st.markdown("---")
                st.subheader("📊 Win Rate Across All Hold Periods")
                hold_rows = []
                for hd in [3, 7, 14, 30]:
                    s = get_backtest_summary(trades, hold_days=hd)
                    if s["total_trades"] > 0:
                        hold_rows.append({
                            "Hold Period": f"{hd}d",
                            "Win Rate %":  s["win_rate"],
                            "Avg Return %": s["avg_return"],
                            "Trades":      s["total_trades"]
                        })
                if hold_rows:
                    hdf = pd.DataFrame(hold_rows).set_index("Hold Period")
                    st.bar_chart(hdf["Win Rate %"])
                    st.dataframe(hdf, use_container_width=True)

                st.markdown("---")
                st.subheader("🏷️ Performance by Ticker")
                if summary["by_ticker"]:
                    ticker_df = pd.DataFrame(summary["by_ticker"])
                    ticker_df["win_rate"] = ticker_df["win_rate"].apply(lambda x: f"{x}%")
                    ticker_df["avg_return"] = ticker_df["avg_return"].apply(lambda x: f"{x:+.2f}%")
                    st.dataframe(ticker_df.rename(columns={
                        "ticker": "Ticker", "trades": "Trades",
                        "win_rate": "Win Rate", "avg_return": "Avg Return",
                        "wins": "✅ Wins", "losses": "❌ Losses"
                    }), use_container_width=True)

                st.markdown("---")
                st.subheader(f"📋 Full Trade Log ({hold_days}-Day Hold)")
                key = f"{hold_days}d"
                trade_rows = []
                for trade in trades:
                    outcome = trade["outcomes"].get(key)
                    if not outcome:
                        continue
                    trade_rows.append({
                        "Ticker":     f"{ticker_icon(trade['ticker'])}{trade['ticker']}",
                        "Date":       trade["date"],
                        "Signal":     f"{'🟢' if trade['sentiment'] == 'bullish' else '🔴'} {trade['sentiment'].upper()}",
                        "Conviction": trade["conviction"].upper(),
                        "Conf %":     f"{trade['confidence']}%",
                        "Entry":      f"${trade['entry']}",
                        "Exit":       f"${outcome['exit']}",
                        "Return":     f"{outcome['pct_change']:+.2f}%",
                        "Result":     outcome["result"],
                        "Source":     trade["source"][:30]
                    })
                if trade_rows:
                    st.dataframe(pd.DataFrame(trade_rows), use_container_width=True)

        except ImportError:
            st.error("❌ Missing `backtester.py` — make sure it's in your project folder.")
