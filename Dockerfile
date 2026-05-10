FROM python:3.12-slim

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# install requirements
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# copy project
COPY . .

# better logs
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
