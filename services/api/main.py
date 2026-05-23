from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.database.session import SessionLocal
from shared.models.events import Event
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@app.get("/events")
async def get_events(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Event))
    events = result.scalars().all()

    return {
        "count": len(events),
        "data": [
            {
                "id": e.id,
                "trace_id": e.trace_id,
                "data": e.data
            }
            for e in events
        ]
    }