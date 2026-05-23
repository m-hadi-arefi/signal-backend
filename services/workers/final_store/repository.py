from sqlalchemy.ext.asyncio import AsyncSession
from shared.models.events import Event


class EventRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_event(self, event: dict):
        obj = Event(
            trace_id=event["trace_id"],
            data=event
        )

        await self.session.merge(obj)
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()