#!/bin/sh

echo "Waiting for Postgres..."

python << END
import time
import psycopg2

while True:
    try:
        psycopg2.connect(
            dbname="events",
            user="postgres",
            password="postgres",
            host="postgres",
            port=5432
        )
        break
    except:
        time.sleep(2)

print("DB is ready")
END

echo "Waiting for Kafka..."
python core/bootstrap.py


echo "Running migrations..."
alembic upgrade head


echo "Starting app..."
exec "$@"