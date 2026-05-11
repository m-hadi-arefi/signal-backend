from sqlalchemy import Column, String, Integer, JSON
from shared.database.base import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String, unique=True, index=True)

    data = Column(JSON)