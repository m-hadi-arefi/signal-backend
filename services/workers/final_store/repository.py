from shared.database.session import SessionLocal
from shared.models.events import Event


class EventRepository:

    def __init__(self):
        self.db = SessionLocal()

    def upsert_event(self, event: dict):
        obj = Event(
            trace_id=event["trace_id"],
            data=event
        )

        self.db.merge(obj)

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()