
import psycopg2
from psycopg2.extras import RealDictCursor
from core.config import settings
import time

def get_connection(retries=5, delay=2):
    for i in range(retries):
        try:
            print(f"settiing POSTGRES_DB :  {settings.POSTGRES_DB}")
            print(f"settiing POSTGRES_USER :  {settings.POSTGRES_USER}")
            print(f"settiing POSTGRES_PASSWORD :  {settings.POSTGRES_PASSWORD}")
            print(f"settiing POSTGRES_HOST :  {settings.POSTGRES_HOST}")
            return psycopg2.connect(
                dbname=settings.POSTGRES_DB,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                host=settings.POSTGRES_HOST
            )
        except psycopg2.OperationalError:
            print(f"settiing POSTGRES_DB :  {settings.POSTGRES_DB}")
            print(f"settiing POSTGRES_USER :  {settings.POSTGRES_USER}")
            print(f"settiing POSTGRES_PASSWORD :  {settings.POSTGRES_PASSWORD}")
            print(f"settiing POSTGRES_HOST :  {settings.POSTGRES_HOST}")
            
            print(f"Postgres not ready, retrying in {delay}s...")
            time.sleep(delay)
    raise


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            data JSONB
        );
    """)

    conn.commit()
    conn.close()