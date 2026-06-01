#!/bin/sh

echo "Waiting for Postgres and ensuring database exists..."

python << 'PYEOF'
import os, time, psycopg2

host = os.environ.get("POSTGRES_HOST", "postgres")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
dbname = os.environ.get("POSTGRES_DB", "events")
user = os.environ.get("POSTGRES_USER", "postgres")
password = os.environ.get("POSTGRES_PASSWORD", "postgres")

while True:
    try:
        conn = psycopg2.connect(dbname="postgres", user=user, password=password, host=host, port=port)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (dbname,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{dbname}"')
            print(f"Database '{dbname}' created.")
        else:
            print(f"Database '{dbname}' already exists.")
        conn.close()
        break
    except Exception as e:
        print(f"Waiting for DB: {e}")
        time.sleep(2)

print("DB is ready")
PYEOF

echo "Running migrations..."
alembic upgrade head

echo "Starting app..."
exec "$@"
