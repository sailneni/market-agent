import os, json, glob
from datetime import datetime, timedelta
from config import REPORTS_DIR

SECTOR_MAP = {
    "NVDA": "Semiconductors", "AMD":  "Semiconductors", "INTC": "Semiconductors",
    "QCOM": "Semiconductors", "AVGO": "Semiconductors", "MU":   "Semiconductors",
    "SMH":  "Semiconductors", "SOXX": "Semiconductors", "CHPS": "Semiconductors",
    "AAPL": "Technology",     "MSFT": "Technology",     "GOOGL": "Technology",
    "META": "Technology",     "AMZN": "Technology",     "XLK":  "Technology",
    "JPM":  "Financials",     "BAC":  "Financials",     "GS":   "Financials",
    "XLF":  "Financials",
    "XOM":  "Energy",         "CVX":  "Energy",         "XLE":  "Energy",
    "JNJ":  "Health Care",    "PFE":  "Health Care",    "XLV":  "Health Care",
    "XLU":  "Utilities",
    "GOLD": "Precious Metals","SILVER": "Precious Metals","GLD": "Precious Metals",
    "SLV":  "Precious Metals","SIL":  "Precious Metals","SILJ": "Precious Metals",
    "SVR.TO": "Precious Metals",
    "XEQT": "Broad Market",   "VFV":  "Broad Market",  "SPY":  "Broad Market",
    "QQQ":  "Broad Market",   "VTI":  "Broad Market",  "VDY":  "Broad Market",
    "TSLA": "EV/Auto",        "RIVN": "EV/Auto",
    "BTC":  "Crypto",         "ETH":  "Crypto",
}


def build_rotation_data(reports: list = None, days: int = 7) -> dict:
    if reports is None:
        reports = []
        for f in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True):
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                continue

    cutoff  = datetime.now() - timedelta(days=days)
    sectors = {}

    for r in reports:
        try:
            ts = datetime.strptime(r.get("analyzed_at", "")[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        if ts < cutoff:
            continue
        for t in r.get("analysis", {}).get("tickers", []):
            tk   = (t.get("ticker") or "").upper()
            sent = (t.get("sentiment") or "neutral").lower()
            sec  = SECTOR_MAP.get(tk, "Other")
            if sec not in sectors:
                sectors[sec] = {"bullish": 0, "bearish": 0, "neutral": 0, "tickers": set()}
            sectors[sec][sent] = sectors[sec].get(sent, 0) + 1
            sectors[sec]["tickers"].add(tk)

    result = {}
    for sec, data in sectors.items():
        total = data["bullish"] + data["bearish"] + data["neutral"]
        score = round((data["bullish"] - data["bearish"]) / total * 10, 1) if total else 0
        result[sec] = {
            "bullish": data["bullish"], "bearish": data["bearish"], "neutral": data["neutral"],
            "score": score, "tickers": list(data["tickers"]),
        }
    return result


def get_sector_summary(rotation_data: dict) -> list:
    return sorted(
        [{"sector": s, **v} for s, v in rotation_data.items()],
        key=lambda x: x["score"], reverse=True,
    )
