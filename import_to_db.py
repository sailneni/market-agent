import os
import json
import glob
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"sslmode": "require"},
    pool_pre_ping=True
)
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def parse_date(ts):
    try:
        return datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
    except Exception:
        return None


def import_reports():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")))
    print(f"Found {len(files)} report files...")

    inserted = 0
    skipped  = 0

    with engine.connect() as conn:
        for file in files:
            try:
                with open(file, "r") as f:
                    r = json.load(f)
            except Exception:
                continue

            analyzed_at       = parse_date(r.get("analyzed_at", ""))
            video             = r.get("video", {})
            analysis          = r.get("analysis", {})
            video_id          = (video.get("video_id") or "").strip() or None
            channel           = video.get("channel", "N/A")
            title             = video.get("title", "")[:200]
            confidence        = analysis.get("confidence_score", 0) or 0
            overall_sentiment = (analysis.get("overall_market_sentiment") or "neutral").lower().strip()
            raw_file          = os.path.basename(file)

            price_data     = json.dumps(r.get("price_data",     {}))
            news_data      = json.dumps(r.get("news_data",      {}))
            tech_data      = json.dumps(r.get("tech_data",      {}))
            market_context = json.dumps(r.get("market_context", {}))

            # ── Dedup check ───────────────────────────────────
            existing = conn.execute(text("""
                SELECT id FROM reports
                WHERE raw_file = :raw_file
                LIMIT 1
            """), {"raw_file": raw_file}).fetchone()

            if existing:
                skipped += 1
                continue

            # ── Insert report ─────────────────────────────────
            result = conn.execute(text("""
                INSERT INTO reports (
                    video_id, analyzed_at, channel, title, confidence,
                    overall_sentiment, price_data, news_data, tech_data,
                    market_context, raw_file
                )
                VALUES (
                    :video_id, :analyzed_at, :channel, :title, :confidence,
                    :overall_sentiment,
                    CAST(:price_data     AS jsonb),
                    CAST(:news_data      AS jsonb),
                    CAST(:tech_data      AS jsonb),
                    CAST(:market_context AS jsonb),
                    :raw_file
                )
                RETURNING id
            """), {
                "video_id":          video_id,
                "analyzed_at":       analyzed_at,
                "channel":           channel,
                "title":             title,
                "confidence":        confidence,
                "overall_sentiment": overall_sentiment,
                "price_data":        price_data,
                "news_data":         news_data,
                "tech_data":         tech_data,
                "market_context":    market_context,
                "raw_file":          raw_file
            })
            report_id = result.fetchone()[0]

            # ── Insert signals ────────────────────────────────
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

            inserted += 1

        conn.commit()

    print(f"✅ Import complete! {inserted} inserted, {skipped} skipped (already in DB)")


if __name__ == "__main__":
    import_reports()
