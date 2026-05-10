from core.kafka import get_producer
import json

producer = get_producer()


def replay_event(event):
    event["pipeline"] = ["html"]

    producer.send("html-events", event)
    producer.flush()