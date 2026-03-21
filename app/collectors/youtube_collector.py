from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
from app.config import settings

youtube = build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)

def get_latest_videos(channel_id: str, max_results: int = 5):
    """Fetch latest video IDs from a channel."""
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video"
    )
    response = request.execute()
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"]
        }
        for item in response.get("items", [])
    ]

def get_transcript(video_id: str) -> str:
    """Fetch full transcript for a YouTube video."""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join([t["text"] for t in transcript])
    except Exception as e:
        return f"Transcript unavailable: {e}"
