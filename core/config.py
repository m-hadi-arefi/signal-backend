import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Required environment variable '{key}' is not set")
    return v


class Settings:
    KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "signals")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = _require("POSTGRES_PASSWORD")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))

    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

settings = Settings()