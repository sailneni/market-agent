import os, json, re, time, random, glob, subprocess, http.cookiejar
import requests
from datetime import datetime
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from config import YOUTUBE_API_KEY, BASE_DIR

SEEN_FILE = os.path.join(BASE_DIR, "seen_videos.json")


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def get_latest_videos(channel_id: str, max_results: int = 5) -> list:
    try:
        yt   = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        resp = yt.search().list(
            part="snippet", channelId=channel_id,
            maxResults=max_results, order="date", type="video"
        ).execute()
        return [
            {
                "video_id":     item["id"]["videoId"],
                "title":        item["snippet"]["title"],
                "channel":      item["snippet"]["channelTitle"],
                "published_at": item["snippet"]["publishedAt"],
                "url":          f"https://youtube.com/watch?v={item['id']['videoId']}",
                "type":         "youtube",
            }
            for item in resp.get("items", [])
        ]
    except Exception as e:
        print(f"  ❌ YouTube API error ({channel_id}): {e}")
        return []


def get_transcript(video_id: str) -> str:
    time.sleep(random.uniform(2, 5))

    # Primary: YouTubeTranscriptApi
    try:
        session    = requests.Session()
        cookie_path = os.path.join(BASE_DIR, "cookies.txt")
        if os.path.exists(cookie_path):
            cj = http.cookiejar.MozillaCookieJar(cookie_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        fetched = YouTubeTranscriptApi(http_client=session).fetch(video_id)
        return " ".join(t.text for t in fetched)
    except Exception as e:
        print(f"  ⚠️  Transcript API failed: {e}")

    # Fallback: yt-dlp
    try:
        tmp = os.path.join(BASE_DIR, f"tmp_{video_id}")
        cmd = [
            "yt-dlp", "--write-auto-sub", "--sub-lang", "en",
            "--skip-download", "--sub-format", "vtt",
            "-o", tmp, "--quiet",
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        cookie_path = os.path.join(BASE_DIR, "cookies.txt")
        if os.path.exists(cookie_path):
            cmd += ["--cookies", cookie_path]
        subprocess.run(cmd, capture_output=True, timeout=30)
        matches = glob.glob(f"{tmp}*.vtt")
        if not matches:
            return ""
        with open(matches[0], encoding="utf-8") as f:
            lines = f.readlines()
        os.remove(matches[0])
        text = [
            l.strip() for l in lines
            if l.strip()
            and "WEBVTT" not in l and "NOTE" not in l
            and "-->" not in l and not l.strip().isdigit()
        ]
        return re.sub(r'\b(\w+)( \1\b)+', r'\1', " ".join(text))
    except Exception as e:
        print(f"  ⚠️  yt-dlp fallback failed: {e}")
        return ""
