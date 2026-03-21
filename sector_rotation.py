import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


SECTOR_MAP = {
    # Semiconductors
    "SMH": "Semiconductors", "SOXX": "Semiconductors", "NVDA": "Semiconductors",
    "AMD": "Semiconductors", "INTC": "Semiconductors", "TSM": "Semiconductors",
    "CHPS": "Semiconductors", "SOXQ": "Semiconductors", "AVGO": "Semiconductors",
    "QCOM": "Semiconductors", "MU": "Semiconductors", "AMAT": "Semiconductors",

    # Technology
    "XLK": "Technology", "QQQ": "Technology", "AAPL": "Technology",
    "MSFT": "Technology", "GOOGL": "Technology", "META": "Technology",
    "AMZN": "Technology", "NFLX": "Technology", "CRM": "Technology",
    "ORCL": "Technology", "ADBE": "Technology",

    # Financials
    "XLF": "Financials", "JPM": "Financials", "BAC": "Financials",
    "GS": "Financials", "MS": "Financials", "WFC": "Financials",
    "V": "Financials", "MA": "Financials", "BRK.B": "Financials",

    # Energy
    "XLE": "Energy", "XOM": "Energy", "CVX": "Energy",
    "COP": "Energy", "SLB": "Energy", "OXY": "Energy",

    # Health Care
    "XLV": "Health Care", "JNJ": "Health Care", "UNH": "Health Care",
    "PFE": "Health Care", "ABBV": "Health Care", "MRK": "Health Care",
    "LLY": "Health Care",

    # Utilities
    "XLU": "Utilities", "NEE": "Utilities", "DUK": "Utilities",
    "SO": "Utilities", "AEP": "Utilities",

    # Precious Metals
    "GLD": "Precious Metals", "SLV": "Precious Metals", "GC=F": "Precious Metals",
    "SI=F": "Precious Metals", "SIL": "Precious Metals", "SILJ": "Precious Metals",
    "SVR.TO": "Precious Metals", "CEF": "Precious Metals",
    "GOLD": "Precious Metals", "SILVER": "Precious Metals",

    # Broad Market / ETFs
    "SPY": "Broad Market", "VTI": "Broad Market", "XEQT": "Broad Market",
    "XGRO": "Broad Market", "VFV": "Broad Market", "VOO": "Broad Market",
    "VDY": "Broad Market",

    # Consumer
    "XLY": "Consumer Disc.", "XLP": "Consumer Staples",
    "TSLA": "Consumer Disc.", "WMT": "Consumer Staples", "COST": "Consumer Staples",

    # Real Estate
    "XLRE": "Real Estate", "VNQ": "Real Estate",

    # Cash / Fixed Income
    "CASH.TO": "Cash/Fixed Income", "PSA.TO": "Cash/Fixed Income",
    "TLT": "Cash/Fixed Income", "BND": "Cash/Fixed Income",
}

WEEK_LABELS = ["4w ago", "3w ago", "2w ago", "Last week", "This week"]


def get_sector(ticker):
    return SECTOR_MAP.get(ticker.upper(), "Other")


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
                SELECT r.id, r.analyzed_at,
                       s.ticker, s.sentiment
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
                    "analysis": {"tickers": []}
                }
            if row[2]:
                report_map[rid]["analysis"]["tickers"].append({
                    "ticker":    row[2],
                    "sentiment": row[3] or "neutral"
                })

        reports = list(report_map.values())
        print(f"  🗄️  Loaded {len(reports)} reports from DB (sector rotation)")
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

def build_rotation_data(reports=None, weeks=5):
    """
    Returns weekly sector sentiment scores.
    score = (bullish - bearish) / total  → range -1.0 to +1.0
    """
    if reports is None:
        reports = _load_reports()

    now    = datetime.now()
    result = {}

    for week_offset in range(weeks - 1, -1, -1):
        week_start = now - timedelta(weeks=week_offset + 1)
        week_end   = now - timedelta(weeks=week_offset)
        label      = WEEK_LABELS[weeks - 1 - week_offset]

        sector_signals = defaultdict(lambda: {"bull": 0, "bear": 0, "neutral": 0})

        for r in reports:
            ts = r.get("analyzed_at", "")
            try:
                if len(ts) >= 15:
                    rt = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
                    if not (week_start <= rt < week_end):
                        continue
                else:
                    continue
            except Exception:
                continue

            for t in r.get("analysis", {}).get("tickers", []):
                ticker    = (t.get("ticker") or "").upper().strip()
                sentiment = (t.get("sentiment") or "neutral").lower().strip()
                if sentiment not in ("bullish", "bearish", "neutral"):
                    sentiment = "neutral"
                if not ticker:
                    continue

                sector = get_sector(ticker)
                if sentiment == "bullish":
                    sector_signals[sector]["bull"] += 1
                elif sentiment == "bearish":
                    sector_signals[sector]["bear"] += 1
                else:
                    sector_signals[sector]["neutral"] += 1

        for sector, counts in sector_signals.items():
            total = counts["bull"] + counts["bear"] + counts["neutral"]
            score = round((counts["bull"] - counts["bear"]) / total, 3) if total > 0 else 0.0
            if sector not in result:
                result[sector] = {}
            result[sector][label] = score

    return result, WEEK_LABELS


def get_sector_summary(reports=None, days=7):
    """
    Returns current sector ranking by net sentiment score (-10 to +10).
    """
    if reports is None:
        reports = _load_reports()

    cutoff  = datetime.now() - timedelta(days=days)
    signals = defaultdict(lambda: {"bull": 0, "bear": 0, "neutral": 0, "tickers": set()})

    for r in reports:
        ts = r.get("analyzed_at", "")
        try:
            if len(ts) >= 15:
                rt = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
                if rt < cutoff:
                    continue
        except Exception:
            pass

        for t in r.get("analysis", {}).get("tickers", []):
            ticker    = (t.get("ticker") or "").upper().strip()
            sentiment = (t.get("sentiment") or "neutral").lower().strip()
            if sentiment not in ("bullish", "bearish", "neutral"):
                sentiment = "neutral"
            if not ticker:
                continue

            sector = get_sector(ticker)
            if sentiment == "bullish":   signals[sector]["bull"]    += 1
            elif sentiment == "bearish": signals[sector]["bear"]    += 1
            else:                        signals[sector]["neutral"] += 1
            signals[sector]["tickers"].add(ticker)

    summary = []
    for sector, s in signals.items():
        total = s["bull"] + s["bear"] + s["neutral"]
        if total == 0:
            continue
        score = round((s["bull"] - s["bear"]) / total * 10, 2)
        summary.append({
            "sector":  sector,
            "score":   score,
            "bull":    s["bull"],
            "bear":    s["bear"],
            "neutral": s["neutral"],
            "total":   total,
            "tickers": sorted(s["tickers"]),
            "bias":    "🟢 Bullish" if score > 2 else "🔴 Bearish" if score < -2 else "🟡 Neutral"
        })

    return sorted(summary, key=lambda x: x["score"], reverse=True)
