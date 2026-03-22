import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
FINNHUB_API_KEY    = os.getenv("FINNHUB_API_KEY", "")
NEWS_API_KEY       = os.getenv("NEWS_API_KEY", "")
MARKETAUX_API_KEY  = os.getenv("MARKETAUX_API_KEY", "")
NEWSDATA_API_KEY   = os.getenv("NEWSDATA_API_KEY", "")
DATABASE_URL       = os.getenv("DATABASE_URL", "")
REDIS_URL          = os.getenv("REDIS_URL", "")

# ── YouTube Channels ──────────────────────────────────────────────────────────
YOUTUBE_CHANNEL_IDS = [
    c.strip()
    for c in os.getenv("YOUTUBE_CHANNEL_IDS", "").split(",")
    if c.strip()
]

# ── Tunable Settings ──────────────────────────────────────────────────────────
WATCHER_INTERVAL_MIN = int(os.getenv("WATCHER_INTERVAL_MIN", "30"))
MIN_CONFIDENCE       = float(os.getenv("MIN_CONFIDENCE", "0.5"))
EVAL_DAYS            = int(os.getenv("EVAL_DAYS", "5"))

# ── Asset Constants ───────────────────────────────────────────────────────────
COMMODITY_TICKERS = {
    "GOLD": "GC=F", "SILVER": "SI=F",
    "XAU":  "GC=F", "XAG":   "SI=F",
    "GLD":  "GLD",  "SLV":   "SLV",
    "SVR.TO": "SVR.TO",
}
COMMODITY_KEYWORDS = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}
SKIP_TECHNICALS    = {"GOLD", "SILVER", "XAU", "XAG", "GC=F", "SI=F"}

ETF_TICKERS = {
    "XEQT", "XGRO", "XBAL", "VFV", "VOO", "SPY", "QQQ", "VTI",
    "VDY", "XEI", "ZDV", "CASH.TO", "PSA.TO",
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLU",
    "CHPS", "SOXQ", "GLD", "SLV", "SIL", "SILJ", "SVR.TO", "CEF",
    "TQQQ", "SQQQ", "UPRO", "SPXU",
}

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
