"""
watcher.py — Thin orchestrator. Entry point for the data collection loop.

Responsibilities:
  - Poll YouTube channels and RSS/news feeds on a schedule
  - Deduplicate (skip already-processed content)
  - Hand each new item to app/services/pipeline.py for multi-agent processing

Run:
  python watcher.py --mode feeds      # RSS + NewsAPI only
  python watcher.py --mode youtube    # YouTube channels only
  python watcher.py --mode both       # Everything (default)
"""

import time
import argparse
from datetime import datetime

from app.collectors.youtube import (
    load_seen as yt_load_seen,
    save_seen as yt_save_seen,
    get_latest_videos,
    get_transcript,
)
from app.collectors.feeds import (
    load_seen as feed_load_seen,
    save_seen as feed_save_seen,
    fetch_all,
)
from app.services.pipeline import process
from config import YOUTUBE_CHANNEL_IDS, WATCHER_INTERVAL_MIN


def run_youtube():
    seen = yt_load_seen()
    print(f"\n{'='*60}")
    print(f"📺 YouTube Check — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Channels: {len(YOUTUBE_CHANNEL_IDS)}")

    if not YOUTUBE_CHANNEL_IDS:
        print("   ❌ No YOUTUBE_CHANNEL_IDS in .env")
        return

    for channel_id in YOUTUBE_CHANNEL_IDS:
        print(f"   📡 Checking: {channel_id}")
        for video in get_latest_videos(channel_id):
            if video["video_id"] in seen:
                print(f"   ✅ Already seen: {video['title'][:50]}")
                continue

            print(f"   🆕 New video: {video['title'][:70]}")
            seen.add(video["video_id"])
            yt_save_seen(seen)

            transcript = get_transcript(video["video_id"])
            if not transcript:
                print("   ⚠️  No transcript — skipping")
                continue

            process({
                "id":           video["video_id"],
                "title":        video["title"],
                "body":         transcript,
                "source":       video["channel"],
                "url":          video["url"],
                "published_at": video["published_at"],
                "type":         "youtube",
            })
            time.sleep(5)   # brief pause between videos


def run_feeds():
    seen     = feed_load_seen()
    articles = fetch_all()
    new      = 0

    print(f"\n{'='*60}")
    print(f"📰 Feed Check — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for article in articles:
        if article["id"] in seen:
            continue
        seen.add(article["id"])
        feed_save_seen(seen)

        process({
            "id":           article["id"],
            "title":        article["title"],
            "body":         article["body"],
            "source":       article["source"],
            "url":          article.get("url", ""),
            "published_at": article.get("published_at", ""),
            "type":         article.get("type", "rss"),
        })
        new += 1
        time.sleep(2)   # brief pause between articles

    print(f"   {'✅ Processed ' + str(new) + ' new articles' if new else '😴 No new articles'}")


def main(mode: str = "both"):
    print("=" * 60)
    print("🚀 MARKET INTELLIGENCE WATCHER STARTED")
    print(f"   Mode: {mode.upper()} | Interval: {WATCHER_INTERVAL_MIN} min")
    print("=" * 60)

    while True:
        try:
            if mode in ("youtube", "both"):
                run_youtube()
            if mode in ("feeds", "both"):
                run_feeds()
        except KeyboardInterrupt:
            print("\n👋 Watcher stopped.")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")

        print(f"\n⏰ Next check in {WATCHER_INTERVAL_MIN} minutes...")
        time.sleep(WATCHER_INTERVAL_MIN * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market Intelligence Watcher")
    parser.add_argument(
        "--mode",
        choices=["youtube", "feeds", "both"],
        default="both",
        help="What to watch: youtube, feeds, or both (default: both)",
    )
    args = parser.parse_args()
    main(mode=args.mode)
