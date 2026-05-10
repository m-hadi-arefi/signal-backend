from core.kafka import get_producer
import json
import time

producer = get_producer()

def send_to_dlq(event, error, stage):
    dlq_event = {
        "original_event": event,
        "error": str(error),
        "stage": stage,
        "timestamp": time.time()
    }

    producer.send("dlq-events", dlq_event)
    producer.flush()