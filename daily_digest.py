import os
import json
import glob
import smtplib
import schedule
import time
import yfinance as yf
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from prediction_tracker import get_accuracy_stats, load_predictions
from signal_scorer import score_ticker
from contradiction_detector import detect_contradictions
from watchlist_learner import get_top_tickers

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


# ── Report loaders ────────────────────────────────────────────────────────────

def _load_from_db(hours=None):
    """Load reports from Supabase. If hours is set, filter to last N hours."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            os.environ["DATABASE_URL"],
            connect_args={"sslmode": "require"},
            pool_pre_ping=True
        )
        report_map = {}
        with engine.connect() as conn:
            if hours:
                cutoff = datetime.now() - timedelta(hours=hours)
                rows = conn.execute(text("""
                    SELECT r.id, r.video_id, r.analyzed_at, r.channel, r.title,
                           r.confidence, r.overall_sentiment,
                           s.ticker, s.sentiment, s.conviction
                    FROM reports r
                    LEFT JOIN signals s ON s.report_id = r.id
                    WHERE r.analyzed_at >= :cutoff
                    ORDER BY r.analyzed_at DESC
                """), {"cutoff": cutoff}).fetchall()
            else:
                rows = conn.execute(text("""
                    SELECT r.id, r.video_id, r.analyzed_at, r.channel, r.title,
                           r.confidence, r.overall_sentiment,
                           s.ticker, s.sentiment, s.conviction
                    FROM reports r
                    LEFT JOIN signals s ON s.report_id = r.id
                    ORDER BY r.analyzed_at DESC
                    LIMIT 1000
                """)).fetchall()

        for row in rows:
            rid = row[0]
            if rid not in report_map:
                report_map[rid] = {
                    "analyzed_at": row[2].strftime("%Y%m%d_%H%M%S") if row[2] else "",
                    "video": {
                        "video_id": row[1] or "",
                        "channel":  row[3] or "N/A",
                        "title":    row[4] or ""
                    },
                    "analysis": {
                        "confidence_score":         float(row[5]) if row[5] else 0,
                        "overall_market_sentiment": row[6] or "neutral",
                        "tickers": []
                    }
                }
            if row[7]:
                report_map[rid]["analysis"]["tickers"].append({
                    "ticker":     row[7],
                    "sentiment":  row[8] or "neutral",
                    "conviction": row[9] or "medium"
                })

        reports = list(report_map.values())
        label   = f"last {hours}h" if hours else "all time"
        print(f"  🗄️  Loaded {len(reports)} reports from DB ({label})")
        return reports

    except Exception as e:
        print(f"  ⚠️  DB unavailable ({e}) — falling back to JSON")
        return None


def _load_from_json(hours=None):
    """Load reports from local JSON files. If hours is set, filter by cutoff."""
    reports = []
    cutoff  = datetime.now() - timedelta(hours=hours) if hours else None
    for file in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
        try:
            with open(file, "r") as f:
                data = json.load(f)
            if cutoff:
                ts = data.get("analyzed_at", "")
                if len(ts) >= 15:
                    report_time = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
                    if report_time < cutoff:
                        continue
            reports.append(data)
        except Exception:
            continue
    print(f"  📂 Loaded {len(reports)} reports from JSON files")
    return reports


def load_recent_reports(hours=24):
    """Load reports from last N hours. DB first, JSON fallback."""
    if os.environ.get("DATABASE_URL"):
        result = _load_from_db(hours=hours)
        if result is not None:
            return result
    return _load_from_json(hours=hours)


def load_all_reports():
    """Load all reports. DB first, JSON fallback."""
    if os.environ.get("DATABASE_URL"):
        result = _load_from_db(hours=None)
        if result is not None:
            return result
    return _load_from_json(hours=None)


# ── Price helper ──────────────────────────────────────────────────────────────

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


# ── Digest builder ────────────────────────────────────────────────────────────

def build_digest_html(reports_24h, all_reports):
    now   = datetime.now().strftime("%A, %B %d %Y — %I:%M %p")
    stats = get_accuracy_stats()
    preds = load_predictions()
    top_tickers    = get_top_tickers(all_reports, top_n=10)
    contradictions = detect_contradictions(all_reports)
    pending_preds  = [p for p in preds if p["outcome"] is None]

    # ── Spot prices ───────────────────────────────────────
    watchlist = [
        ("🥇 Gold",     "GC=F"),
        ("🥈 Silver",   "SI=F"),
        ("📦 XEQT",    "XEQT"),
        ("📦 VDY",     "VDY"),
        ("📦 SMH",     "SMH"),
        ("📦 CHPS",    "CHPS"),
        ("📦 SIL",     "SIL"),
        ("📦 SVR.TO",  "SVR.TO"),
        ("📦 CASH.TO", "CASH.TO"),
    ]
    prices_html = ""
    for label, sym in watchlist:
        price, chg = yf_price(sym)
        if price:
            color  = "#00c853" if chg and chg > 0 else "#ff1744"
            arrow  = "▲" if chg and chg > 0 else "▼"
            prices_html += f"""
            <tr>
                <td style="padding:6px 12px;">{label}</td>
                <td style="padding:6px 12px; font-weight:bold;">${price:,}</td>
                <td style="padding:6px 12px; color:{color};">{arrow} {chg:+.2f}%</td>
            </tr>"""

    # ── Top signals from last 24h ─────────────────────────
    signals_html = ""
    top_signals  = []
    for r in reports_24h:
        for t in r.get("analysis", {}).get("tickers", []):
            ticker     = t.get("ticker", "")
            sentiment  = t.get("sentiment", "neutral")
            conviction = t.get("conviction", "medium")
            confidence = r.get("analysis", {}).get("confidence_score", 0)
            score_data = score_ticker(ticker, [r])
            top_signals.append({
                "ticker":     ticker,
                "sentiment":  sentiment,
                "conviction": conviction,
                "confidence": confidence,
                "score":      score_data.get("total_score", 0),
                "source":     r.get("video", {}).get("channel", "N/A")
            })

    top_signals = sorted(top_signals, key=lambda x: x["score"], reverse=True)[:8]
    for s in top_signals:
        color  = "#00c853" if s["sentiment"] == "bullish" else "#ff1744" if s["sentiment"] == "bearish" else "#ffc107"
        emoji  = "🟢" if s["sentiment"] == "bullish" else "🔴" if s["sentiment"] == "bearish" else "🟡"
        signals_html += f"""
        <tr>
            <td style="padding:6px 12px; font-weight:bold;">{s['ticker']}</td>
            <td style="padding:6px 12px; color:{color};">{emoji} {s['sentiment'].upper()}</td>
            <td style="padding:6px 12px;">{s['conviction'].upper()}</td>
            <td style="padding:6px 12px;">{s['confidence']*100:.0f}%</td>
            <td style="padding:6px 12px;">{s['score']:.1f}/10</td>
            <td style="padding:6px 12px; font-size:12px;">{s['source'][:30]}</td>
        </tr>"""

    if not signals_html:
        signals_html = "<tr><td colspan='6' style='padding:12px; color:#888;'>No signals in last 24h</td></tr>"

    # ── Contradictions ────────────────────────────────────
    contra_html = ""
    for ticker, data in list(contradictions.items())[:5]:
        contra_html += f"""
        <tr>
            <td style="padding:6px 12px; font-weight:bold;">{ticker}</td>
            <td style="padding:6px 12px; color:#00c853;">🟢 {data['bullish']}</td>
            <td style="padding:6px 12px; color:#ff1744;">🔴 {data['bearish']}</td>
            <td style="padding:6px 12px; color:#ffc107;">⚠️ {data['conflict_level'].upper()}</td>
            <td style="padding:6px 12px; font-size:12px;">{data['recommendation']}</td>
        </tr>"""
    if not contra_html:
        contra_html = "<tr><td colspan='5' style='padding:12px; color:#888;'>No conflicting signals</td></tr>"

    # ── Top tickers ───────────────────────────────────────
    trending_html = ""
    for entry in top_tickers[:8]:
        bull_pct  = round(entry["bullish"] / entry["count"] * 100) if entry["count"] else 0
        bar_color = "#00c853" if bull_pct >= 60 else "#ff1744" if bull_pct <= 40 else "#ffc107"
        trending_html += f"""
        <tr>
            <td style="padding:6px 12px; font-weight:bold;">{entry['ticker']}</td>
            <td style="padding:6px 12px;">{entry['count']}</td>
            <td style="padding:6px 12px; color:{bar_color};">{bull_pct}% Bullish</td>
            <td style="padding:6px 12px;">{entry.get('asset_type', 'stock').upper()}</td>
        </tr>"""

    # ── Accuracy ──────────────────────────────────────────
    acc_html = ""
    if stats:
        acc_html = f"""
        <tr><td style="padding:6px 12px;">Overall</td><td style="padding:6px 12px; font-weight:bold;">{stats['accuracy']}%</td><td style="padding:6px 12px;">{stats['correct']}/{stats['total']}</td></tr>
        """
        if stats.get("stock_accuracy")     is not None: acc_html += f"<tr><td style='padding:6px 12px;'>📈 Stocks</td><td style='padding:6px 12px;'>{stats['stock_accuracy']}%</td><td></td></tr>"
        if stats.get("etf_accuracy")       is not None: acc_html += f"<tr><td style='padding:6px 12px;'>📦 ETFs</td><td style='padding:6px 12px;'>{stats['etf_accuracy']}%</td><td></td></tr>"
        if stats.get("commodity_accuracy") is not None: acc_html += f"<tr><td style='padding:6px 12px;'>🥇 Commodities</td><td style='padding:6px 12px;'>{stats['commodity_accuracy']}%</td><td></td></tr>"
    else:
        acc_html = "<tr><td colspan='3' style='padding:12px; color:#888;'>No predictions evaluated yet</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0e1117; color:#e0e0e0; margin:0; padding:0; }}
            .container {{ max-width:800px; margin:0 auto; padding:24px; }}
            .header {{ background: linear-gradient(135deg, #1c1f26, #2a2d3a); border-radius:12px; padding:24px; margin-bottom:24px; border-left:4px solid #00d4aa; }}
            h1 {{ color:#00d4aa; margin:0 0 4px 0; font-size:24px; }}
            .subtitle {{ color:#888; font-size:14px; }}
            .section {{ background:#1c1f26; border-radius:12px; padding:20px; margin-bottom:20px; }}
            h2 {{ color:#00d4aa; font-size:16px; margin:0 0 16px 0; border-bottom:1px solid #333; padding-bottom:8px; }}
            table {{ width:100%; border-collapse:collapse; }}
            tr:nth-child(even) {{ background:#252830; }}
            td {{ color:#e0e0e0; font-size:14px; }}
            .footer {{ text-align:center; color:#555; font-size:12px; margin-top:24px; }}
            .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
        </style>
    </head>
    <body>
    <div class="container">

        <div class="header">
            <h1>📊 Market Intelligence Digest</h1>
            <div class="subtitle">{now} • {len(reports_24h)} reports analyzed in last 24h • {len(pending_preds)} predictions pending</div>
        </div>

        <div class="section">
            <h2>💼 Your Watchlist — Live Prices</h2>
            <table><tbody>{prices_html}</tbody></table>
        </div>

        <div class="section">
            <h2>🔔 Top Signals (Last 24h)</h2>
            <table>
                <thead><tr style="color:#888; font-size:12px;">
                    <th style="padding:6px 12px; text-align:left;">Ticker</th>
                    <th style="padding:6px 12px; text-align:left;">Sentiment</th>
                    <th style="padding:6px 12px; text-align:left;">Conviction</th>
                    <th style="padding:6px 12px; text-align:left;">Confidence</th>
                    <th style="padding:6px 12px; text-align:left;">Score</th>
                    <th style="padding:6px 12px; text-align:left;">Source</th>
                </tr></thead>
                <tbody>{signals_html}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>🔄 Conflicting Signals</h2>
            <table>
                <thead><tr style="color:#888; font-size:12px;">
                    <th style="padding:6px 12px; text-align:left;">Ticker</th>
                    <th style="padding:6px 12px; text-align:left;">Bullish</th>
                    <th style="padding:6px 12px; text-align:left;">Bearish</th>
                    <th style="padding:6px 12px; text-align:left;">Conflict</th>
                    <th style="padding:6px 12px; text-align:left;">Recommendation</th>
                </tr></thead>
                <tbody>{contra_html}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>🔥 Trending Tickers (All Time)</h2>
            <table>
                <thead><tr style="color:#888; font-size:12px;">
                    <th style="padding:6px 12px; text-align:left;">Ticker</th>
                    <th style="padding:6px 12px; text-align:left;">Mentions</th>
                    <th style="padding:6px 12px; text-align:left;">Bias</th>
                    <th style="padding:6px 12px; text-align:left;">Type</th>
                </tr></thead>
                <tbody>{trending_html}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>🧠 Prediction Accuracy</h2>
            <table>
                <thead><tr style="color:#888; font-size:12px;">
                    <th style="padding:6px 12px; text-align:left;">Category</th>
                    <th style="padding:6px 12px; text-align:left;">Accuracy</th>
                    <th style="padding:6px 12px; text-align:left;">Evaluated</th>
                </tr></thead>
                <tbody>{acc_html}</tbody>
            </table>
        </div>

        <div class="footer">
            Market Intelligence Agent • Generated {now}<br>
            This is not financial advice. Always do your own research.
        </div>

    </div>
    </body>
    </html>
    """
    return html


# ── Email sender ──────────────────────────────────────────────────────────────

def send_digest_email(html_content):
    to_email   = os.getenv("DIGEST_EMAIL_TO")
    from_email = os.getenv("DIGEST_EMAIL_FROM")
    password   = os.getenv("DIGEST_EMAIL_PASSWORD")

    if not all([to_email, from_email, password]):
        print("  ⚠️  Email credentials not set — saving digest as HTML only")
        filename = os.path.join(BASE_DIR, f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(filename, "w") as f:
            f.write(html_content)
        print(f"  💾 Digest saved → {filename}")
        return

    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 Market Digest — {datetime.now().strftime('%b %d, %Y')}"
        msg["From"]    = from_email
        msg["To"]      = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_email, password)
            server.sendmail(from_email, to_email, msg.as_string())

        print(f"  ✅ Digest emailed to {to_email}")
    except Exception as e:
        print(f"  ❌ Email failed: {e}")
        filename = os.path.join(BASE_DIR, f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(filename, "w") as f:
            f.write(html_content)
        print(f"  💾 Fallback: saved → {filename}")


# ── Runner & scheduler ────────────────────────────────────────────────────────

def run_digest():
    print(f"\n📧 Generating daily digest at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    all_reports = load_all_reports()
    reports_24h = load_recent_reports(hours=24)
    html        = build_digest_html(reports_24h, all_reports)
    send_digest_email(html)


def run_scheduler(send_time="08:00"):
    print(f"📅 Daily Digest Scheduler started — will send at {send_time} every day")
    schedule.every().day.at(send_time).do(run_digest)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "now":
        run_digest()
    else:
        run_scheduler(send_time="08:00")
