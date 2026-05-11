import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "events")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))

    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

settings = Settings()