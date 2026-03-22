import os, json, logging
from datetime import datetime
from config import REPORTS_DIR, DATABASE_URL

logger = logging.getLogger(__name__)
_engine = None


def _get_engine():
    global _engine
    if _engine is None and DATABASE_URL:
        try:
            from sqlalchemy import create_engine
            _engine = create_engine(
                DATABASE_URL,
                connect_args={"sslmode": "require"},
                pool_pre_ping=True,
            )
        except Exception as e:
            logger.warning(f"DB engine creation failed: {e}")
    return _engine


def save_json(report: dict) -> str:
    """Save report to JSON file. Returns filename."""
    ts       = report.get("analyzed_at", datetime.now().strftime("%Y%m%d_%H%M%S"))
    vid_id   = report.get("video", {}).get("video_id", "unknown")[:40].replace("/", "_").replace(":", "_")
    filename = f"{vid_id}_{ts}.json"
    filepath = os.path.join(REPORTS_DIR, filename)
    try:
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  💾 Saved JSON → {filename}")
    except Exception as e:
        print(f"  ⚠️  JSON save failed: {e}")
    return filename


def save_db(report: dict) -> bool:
    """Save report to database. Returns True on success."""
    engine = _get_engine()
    if not engine:
        return False
    try:
        from sqlalchemy import text
        video    = report.get("video", {})
        analysis = report.get("analysis", {})
        ts       = report.get("analyzed_at", "")
        try:
            analyzed_at = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
        except Exception:
            analyzed_at = datetime.now()

        with engine.connect() as conn:
            existing = conn.execute(text(
                "SELECT id FROM reports WHERE raw_file = :f LIMIT 1"
            ), {"f": report.get("_filename", "")}).fetchone()
            if existing:
                return True

            result = conn.execute(text("""
                INSERT INTO reports (
                    video_id, analyzed_at, channel, title, url, source_type,
                    confidence, overall_sentiment,
                    price_data, news_data, tech_data, market_context, sec_data,
                    key_themes, bull_cases, bear_cases, investment_tactics, raw_file
                ) VALUES (
                    :video_id, :analyzed_at, :channel, :title, :url, :source_type,
                    :confidence, :overall_sentiment,
                    CAST(:price_data AS jsonb), CAST(:news_data AS jsonb),
                    CAST(:tech_data AS jsonb), CAST(:market_context AS jsonb),
                    CAST(:sec_data AS jsonb), CAST(:key_themes AS jsonb),
                    CAST(:bull_cases AS jsonb), CAST(:bear_cases AS jsonb),
                    CAST(:investment_tactics AS jsonb), :raw_file
                ) RETURNING id
            """), {
                "video_id":           video.get("video_id"),
                "analyzed_at":        analyzed_at,
                "channel":            video.get("channel", "N/A"),
                "title":              (video.get("title") or "")[:200],
                "url":                (video.get("url") or "")[:500],
                "source_type":        video.get("type", "youtube"),
                "confidence":         analysis.get("confidence_score", 0),
                "overall_sentiment":  (analysis.get("overall_market_sentiment") or "neutral").lower(),
                "price_data":         json.dumps(report.get("price_data",     {})),
                "news_data":          json.dumps(report.get("news_data",      {})),
                "tech_data":          json.dumps(report.get("tech_data",      {})),
                "market_context":     json.dumps(report.get("market_context", {})),
                "sec_data":           json.dumps(report.get("sec_data",       {})),
                "key_themes":         json.dumps(analysis.get("key_themes",         [])),
                "bull_cases":         json.dumps(analysis.get("bull_cases",         [])),
                "bear_cases":         json.dumps(analysis.get("bear_cases",         [])),
                "investment_tactics": json.dumps(analysis.get("investment_tactics", [])),
                "raw_file":           report.get("_filename", ""),
            })
            report_id = result.fetchone()[0]

            for t in analysis.get("tickers", []):
                tk = (t.get("ticker") or "").upper().strip()
                if not tk:
                    continue
                conn.execute(text("""
                    INSERT INTO signals (report_id, ticker, sentiment, conviction, context_text, company)
                    VALUES (:rid, :ticker, :sentiment, :conviction, :ctx, :company)
                """), {
                    "rid":        report_id,
                    "ticker":     tk,
                    "sentiment":  (t.get("sentiment")  or "neutral").lower(),
                    "conviction": (t.get("conviction") or "medium").lower(),
                    "ctx":        (t.get("context")    or "")[:500],
                    "company":    (t.get("company")    or "")[:200],
                })
            conn.commit()
        return True
    except Exception as e:
        logger.warning(f"DB save failed: {e}")
        return False


def save_report(report: dict) -> str:
    """Save to JSON (always) and DB (if available). Returns filename."""
    filename          = save_json(report)
    report["_filename"] = filename
    if DATABASE_URL:
        ok = save_db(report)
        print(f"  🗄️  DB save: {'✅' if ok else '⚠️  failed (JSON backup exists)'}")
    return filename
