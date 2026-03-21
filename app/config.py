from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str
    YOUTUBE_API_KEY: str
    FINNHUB_API_KEY: str
    NEWS_API_KEY: str
    DATABASE_URL: str
    REDIS_URL: str
    YOUTUBE_CHANNEL_IDS: str

    class Config:
        env_file = ".env"

settings = Settings()
