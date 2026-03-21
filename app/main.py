from fastapi import FastAPI
from app.scheduler.watcher import start_scheduler
from app.tasks.celery_tasks import process_video

app = FastAPI(title="Market Intelligence Agent")

@app.on_event("startup")
def startup():
    start_scheduler()

@app.post("/analyze/video")
def analyze_video(video_id: str):
    """Manually trigger analysis for a YouTube video."""
    task = process_video.delay(video_id, "Manual trigger")
    return {"task_id": task.id, "status": "queued"}

@app.get("/signals/{ticker}")
def get_signals(ticker: str):
    """Get all signals for a ticker."""
    # Query DB signals table for ticker
    return {"ticker": ticker, "message": "Query signals from DB here"}
