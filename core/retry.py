import time

def can_retry(event):
    return event.get("retry_count", 0) < event.get("max_retries", 3)


def increase_retry(event):
    event["retry_count"] = event.get("retry_count", 0) + 1
    return event


def retry_delay():
    time.sleep(2)
