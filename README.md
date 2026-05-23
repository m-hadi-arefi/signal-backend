"# signal-backend" 

## Getting Started

### Prerequisites

- Python 3.8+
- Docker
- Docker Compose
- Redis
- Postgres
- Kafka

### Installation

1. Clone the repository
2. Create a `.env` file

### Running the project

1. Start the project
```bash
docker compose -f docker-compose.yml -f docker/kafka-compose.yml -f docker/workers-compose.yml -f docker/producers-compose.yml -f docker/api-compose.yml up -d
```

2. Stop the project
```bash
docker compose -f docker-compose.yml -f docker/kafka-compose.yml -f docker/workers-compose.yml -f docker/producers-compose.yml -f docker/api-compose.yml down
```
