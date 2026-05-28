FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|https://archive.ubuntu.com|http://archive.ubuntu.com|g' /etc/apt/sources.list
RUN apt-get update || true

RUN apt-get install -y --no-install-recommends \
    ca-certificates \
    apt-transport-https \
    curl

RUN update-ca-certificates

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
