from apscheduler.schedulers.background import BackgroundScheduler
from app.collectors.youtube_collector import get_latest_videos
from app.tasks.celery_tasks import process_video
from app.config import settings

seen_video_ids = set()  # Replace with DB lookup in production

def check_new_videos():
    channel_ids = settings.YOUTUBE_CHANNEL_IDS.split(",")
    new_count = 0
    for channel_id in channel_ids:
        videos = get_latest_videos(channel_id)
        for video in videos:
            vid = video["video_id"]
            if vid not in seen_video_ids:
                seen_video_ids.add(vid)
                process_video.delay(vid, video["title"])
                new_count += 1
    print(f"Queued {new_count} new videos for processing")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_new_videos, "interval", minutes=30)
    scheduler.start()
