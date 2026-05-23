from shared.database.engine import engine
from sqlalchemy.ext.asyncio import async_sessionmaker

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False
)