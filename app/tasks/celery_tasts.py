import os
import json
from datetime import datetime
from celery import Celery
from app.collectors.youtube_collector import get_transcript, get_latest_videos
from app.collectors.sec_collector import get_company_filings
from app.collectors.market_collector import get_quote, get_news_sentiment
from app.agents.ticker_extractor import extract_tickers
from app.agents.tactic_agent import generate_tactic
from app.config import settings
from db_writer import save_report_to_db

celery_app = Celery("tasks", broker=settings.REDIS_URL)

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _save_report_json(report: dict) -> str:
    """Save report to JSON file, return filename."""
    filename = f"{report['analyzed_at']}.json"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(report, f, indent=2)
    return filename


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_video(self, video_id: str, title: str, channel: str = "N/A"):
    """Full pipeline for one YouTube video."""
    try:
        transcript = get_transcript(video_id)

        # Handle unavailable transcripts
        if transcript.startswith("Transcript unavailable"):
            return {"error": transcript, "video_id": video_id}

        tickers = extract_tickers(transcript)

        if not tickers:
            return {"error": "No tickers found", "video_id": video_id}

        results = []
        for item in tickers:
            ticker  = item["ticker"]
            price   = get_quote(ticker)
            news    = get_news_sentiment(ticker)
            filings = get_company_filings(ticker)
            signals = [
                {"source": "youtube", "context": item["context"]},
                {"source": "news",    "headlines": news},
                {"source": "sec",     "filings": filings.get("filings", [])},
            ]
            tactic = generate_tactic(ticker, signals, price)
            results.append({
                "ticker": ticker,
                "tactic": tactic,
                "price":  price
            })

        # Build structured report
        report = {
            "analyzed_at": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "video": {
                "video_id": video_id,
                "title":    title,
                "channel":  channel
            },
            "analysis": {
                "confidence_score": None,
                "tickers": [
                    {
                        "ticker":     r["ticker"],
                        "sentiment":  r["tactic"].get("sentiment"),
                        "conviction": r["tactic"].get("conviction"),
                        "tactic":     r["tactic"]
                    }
                    for r in results
                ]
            },
            "results": results
        }

        # Save to JSON first (always — even if DB fails)
        filename            = _save_report_json(report)
        report["_filename"] = filename

        # Save to DB (non-blocking — won't crash pipeline if DB is down)
        save_report_to_db(report)

        return {
            "video_id":   video_id,
            "title":      title,
            "channel":    channel,
            "tickers":    [r["ticker"] for r in results],
            "saved_to":   filename,
            "db_saved":   True
        }

    except Exception as e:
        # Retry up to 3 times on unexpected errors
        raise self.retry(exc=e)


@celery_app.task
def process_channel(channel_id: str, channel_name: str, max_results: int = 5):
    """Fetch and queue latest videos from a channel."""
    videos = get_latest_videos(channel_id, max_results=max_results)
    queued = []

    for video in videos:
        task = process_video.delay(
            video["video_id"],
            video["title"],
            channel_name
        )
        queued.append({
            "video_id": video["video_id"],
            "title":    video["title"],
            "task_id":  task.id
        })

    return {"channel": channel_name, "queued": len(queued), "videos": queued}
