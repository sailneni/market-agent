"""
app/api/main.py — FastAPI REST endpoints.

Run: uvicorn app.api.main:app --reload --port 8000

Endpoints:
  GET /health               — health check
  GET /reports              — list recent reports
  GET /reports/{id}         — full report by filename
  GET /signals              — scored signals across all reports
  GET /tickers/{ticker}     — score + memory for a single ticker
  GET /stats                — prediction accuracy stats
"""

import json, os, glob
from fastapi import FastAPI, HTTPException
from config import REPORTS_DIR

app = FastAPI(
    title="Market Intelligence API",
    description="Real-time market signal extraction and analysis",
    version="1.0.0",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_reports(limit: int = 50) -> list:
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True)[:limit]
    reports = []
    for f in files:
        try:
            with open(f) as fh:
                r = json.load(fh)
                r["_filename"] = os.path.basename(f)
                reports.append(r)
        except Exception:
            continue
    return reports


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    report_count = len(glob.glob(os.path.join(REPORTS_DIR, "*.json")))
    return {"status": "ok", "reports_available": report_count}


@app.get("/reports")
def list_reports(limit: int = 20):
    """List recent analysis reports (summary only)."""
    reports = _load_reports(limit)
    summaries = []
    for r in reports:
        analysis = r.get("analysis", {})
        summaries.append({
            "id":         r["_filename"],
            "analyzed_at": r.get("analyzed_at", ""),
            "title":      r.get("video", {}).get("title", ""),
            "source":     r.get("video", {}).get("channel", ""),
            "type":       r.get("video", {}).get("type", ""),
            "sentiment":  analysis.get("overall_market_sentiment", ""),
            "confidence": analysis.get("confidence_score", 0),
            "tickers":    [t.get("ticker") for t in analysis.get("tickers", [])],
        })
    return {"count": len(summaries), "reports": summaries}


@app.get("/reports/{report_id}")
def get_report(report_id: str):
    """Get the full JSON for a specific report."""
    path = os.path.join(REPORTS_DIR, report_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    with open(path) as f:
        return json.load(f)


@app.get("/signals")
def get_signals(top_n: int = 20):
    """Get scored buy/sell signals across all reports."""
    from app.services.scorer import score_all_tickers
    scores = score_all_tickers()
    items  = list(scores.values())[:top_n]
    return {"count": len(items), "signals": items}


@app.get("/tickers/{ticker}")
def get_ticker(ticker: str):
    """Get score, prediction memory, and recent mentions for a ticker."""
    ticker = ticker.upper()
    from app.services.tracker import get_model_memory
    from app.services.scorer  import score_all_tickers
    scores = score_all_tickers()
    score  = scores.get(ticker, {"ticker": ticker, "avg_score": 0.0, "signal_label": "NO DATA"})
    memory = get_model_memory(ticker)

    # Collect recent mentions from reports
    reports  = _load_reports(30)
    mentions = []
    for r in reports:
        for t in r.get("analysis", {}).get("tickers", []):
            if t.get("ticker", "").upper() == ticker:
                mentions.append({
                    "analyzed_at": r.get("analyzed_at", ""),
                    "source":      r.get("video", {}).get("channel", ""),
                    "sentiment":   t.get("sentiment", ""),
                    "conviction":  t.get("conviction", ""),
                    "reasoning":   t.get("reasoning", ""),
                })

    return {
        "ticker":   ticker,
        "score":    score,
        "memory":   memory,
        "mentions": mentions[:10],
    }


@app.get("/stats")
def get_stats():
    """Get overall prediction accuracy statistics."""
    from app.services.tracker import get_accuracy_stats, print_prediction_report
    stats = get_accuracy_stats()
    if not stats:
        return {"message": "No evaluated predictions yet"}
    return stats
