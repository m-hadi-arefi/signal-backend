from sqlalchemy import Column, Integer, String, Float, DateTime
from shared.database.base import Base
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSON

class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    type = Column(String)  # BUY / SELL
    price = Column(Float)

    source = Column(String)  # telegram / scraper / api
    raw_payload = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)


class SignalResult(Base):
    __tablename__ = "signal_results"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, index=True)

    status = Column(String)  # win / loss / break_even
    pnl = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow)

class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    type = Column(String)