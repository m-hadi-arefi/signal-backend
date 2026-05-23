import asyncpg
import asyncio
from core.config import settings

async def get_connection(retries=5, delay=2):
    for i in range(retries):
        try:
            return await asyncpg.connect(
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                database=settings.POSTGRES_DB,
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT
            )
        except Exception as e:
            print(f"Postgres not ready ({e}), retrying in {delay}s...")
            await asyncio.sleep(delay)
    raise RuntimeError("Could not connect to Postgres")


async def init_db():
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                data JSONB
            );
        """)
        print("[DB] Initialized successfully")
    finally:
        await conn.close()