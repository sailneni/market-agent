import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logger  = logging.getLogger(__name__)
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL not set in environment")
        _engine = create_engine(
            database_url,
            connect_args={"sslmode": "require"},
            pool_pre_ping=True
        )
    return _engine


def save_report_to_db(report: dict) -> bool:
    try:
        engine   = get_engine()
        ts       = report.get("analyzed_at", "")
        video    = report.get("video", {})
        analysis = report.get("analysis", {})

        # ── reports fields ────────────────────────────
        video_id            = (video.get("video_id") or "").strip() or None
        channel             = video.get("channel", "N/A")
        title               = video.get("title", "")[:200]
        url                 = video.get("url", "")[:500]
        source_type         = video.get("type", "youtube")
        confidence          = analysis.get("confidence_score", 0) or 0
        overall_sentiment   = (analysis.get("overall_market_sentiment") or "neutral").lower().strip()
        raw_file            = report.get("_filename", "")

        # ── JSONB fields ──────────────────────────────
        price_data          = json.dumps(report.get("price_data",      {}))
        news_data           = json.dumps(report.get("news_data",       {}))
        tech_data           = json.dumps(report.get("tech_data",       {}))
        market_context      = json.dumps(report.get("market_context",  {}))
        sec_data            = json.dumps(report.get("sec_data",        {}))
        key_themes          = json.dumps(analysis.get("key_themes",         []))
        bull_cases          = json.dumps(analysis.get("bull_cases",         []))
        bear_cases          = json.dumps(analysis.get("bear_cases",         []))
        investment_tactics  = json.dumps(analysis.get("investment_tactics", []))

        # ── Timestamps ───────────────────────────────
        try:
            analyzed_at = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
        except Exception:
            analyzed_at = datetime.now()

        try:
            published_at = datetime.fromisoformat(
                video.get("published_at", "").replace("Z", "+00:00")
            )
        except Exception:
            published_at = None

        with engine.connect() as conn:

            # ── Dedup check ───────────────────────────
            existing = conn.execute(text("""
                SELECT id FROM reports
                WHERE raw_file = :raw_file
                LIMIT 1
            """), {"raw_file": raw_file}).fetchone()

            if existing:
                logger.info(f"⏭️  Already in DB (skipped): {title[:50]}")
                return True

            # ── Insert report ─────────────────────────
            result = conn.execute(text("""
                INSERT INTO reports (
                    video_id, analyzed_at, published_at, channel, title,
                    url, source_type, confidence, overall_sentiment,
                    price_data, news_data, tech_data, market_context,
                    sec_data, key_themes, bull_cases, bear_cases,
                    investment_tactics, raw_file
                )
                VALUES (
                    :video_id, :analyzed_at, :published_at, :channel, :title,
                    :url, :source_type, :confidence, :overall_sentiment,
                    CAST(:price_data         AS jsonb),
                    CAST(:news_data          AS jsonb),
                    CAST(:tech_data          AS jsonb),
                    CAST(:market_context     AS jsonb),
                    CAST(:sec_data           AS jsonb),
                    CAST(:key_themes         AS jsonb),
                    CAST(:bull_cases         AS jsonb),
                    CAST(:bear_cases         AS jsonb),
                    CAST(:investment_tactics AS jsonb),
                    :raw_file
                )
                RETURNING id
            """), {
                "video_id":           video_id,
                "analyzed_at":        analyzed_at,
                "published_at":       published_at,
                "channel":            channel,
                "title":              title,
                "url":                url,
                "source_type":        source_type,
                "confidence":         confidence,
                "overall_sentiment":  overall_sentiment,
                "price_data":         price_data,
                "news_data":          news_data,
                "tech_data":          tech_data,
                "market_context":     market_context,
                "sec_data":           sec_data,
                "key_themes":         key_themes,
                "bull_cases":         bull_cases,
                "bear_cases":         bear_cases,
                "investment_tactics": investment_tactics,
                "raw_file":           raw_file
            })
            report_id = result.fetchone()[0]

            # ── Insert signals ────────────────────────
            for t in analysis.get("tickers", []):
                ticker       = (t.get("ticker")    or "").upper().strip()
                sentiment    = (t.get("sentiment")  or "neutral").lower()
                conviction   = (t.get("conviction") or "medium").lower()
                context_text = (t.get("context")    or "")[:500]
                company      = (t.get("company")    or "")[:200]

                if not ticker:
                    continue

                conn.execute(text("""
                    INSERT INTO signals (
                        report_id, ticker, sentiment, conviction, context_text, company
                    )
                    VALUES (
                        :report_id, :ticker, :sentiment, :conviction, :context_text, :company
                    )
                """), {
                    "report_id":    report_id,
                    "ticker":       ticker,
                    "sentiment":    sentiment,
                    "conviction":   conviction,
                    "context_text": context_text,
                    "company":      company
                })

            conn.commit()

        logger.info(f"✅ Saved to DB: {channel} — {title[:50]}")
        return True

    except Exception as e:
        logger.warning(f"⚠️ Failed to save report to DB: {e}")
        return False
