from core.kafka_client import get_consumer

def create_consumer():
    return get_consumer("final-events", "final-group")