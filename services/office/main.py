from fastapi import FastAPI
from core.redis import get_redis
from core.heartbeat import is_alive
from services.office.replay import replay_event

app = FastAPI()
redis = get_redis()


@app.get("/health/{service}")
def health(service: str):
    return {"service": service, "alive": is_alive(service)}


@app.post("/replay")
async def replay(event: dict):
    await replay_event(event)
    return {"status": "replayed"}


@app.get("/dlq")
def get_dlq():
    keys = redis.keys("*dlq*")
    return {"dlq_keys": keys}

@app.get("/trace/{trace_id}")
def trace(trace_id: str):
    keys = redis.keys(f"*{trace_id}*")
    return {"trace": keys}