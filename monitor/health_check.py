from core.heartbeat import is_alive

services = ["html_worker", "ai_worker", "serializer"]

for s in services:
    print(s, "alive:", is_alive(s))