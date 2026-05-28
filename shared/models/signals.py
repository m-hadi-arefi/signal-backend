from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from shared.database.base import Base


class Signal(Base):
    """
    Top-level record for one trading signal analysis.

    One Signal per (trace_id, symbol) pair — if an analysis mentions
    both BTC and ETH, two Signal rows are created under the same trace_id.

    Each Signal has one or more Scenario rows representing the possible
    trading opportunities extracted by the AI (e.g. breakout long,
    rejection short, invalidation).
    """
    __tablename__ = "signals"

    id       = Column(Integer, primary_key=True)
    symbol   = Column(String(20), nullable=False)
    trace_id = Column(String(36), nullable=False)

    # Source provenance — JSONB: {type, provider, channel?, url?, external_id?}
    source = Column(JSONB, nullable=False)

    # Original and summarised text from the analysis message
    raw_text   = Column(Text)
    ai_summary = Column(Text)

    # Market price snapshotted from Redis at the moment of storage.
    # Nullable: Redis miss is acceptable — worker logs a warning and stores NULL.
    # Shape: {price: float, source: str, timestamp: str}
    current_market_price = Column(JSONB)

    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    analyzed_at = Column(DateTime)

    scenarios = relationship(
        "Scenario",
        back_populates="signal",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_signals_symbol",          "symbol"),
        Index("ix_signals_trace_id",        "trace_id"),
        Index("ix_signals_created_at",      "created_at"),
        Index("ix_signals_symbol_created",  "symbol", "created_at"),
        # GIN index enables WHERE source @> '{"provider":"x"}'::jsonb
        Index("ix_signals_source_gin", "source", postgresql_using="gin"),
    )


class Scenario(Base):
    """
    One tradeable scenario within a Signal.

    Fields mirror what the AI extracts: entry, targets, stop, confidence,
    reasoning, and the current lifecycle status.
    """
    __tablename__ = "scenarios"

    id        = Column(Integer, primary_key=True)
    signal_id = Column(
        Integer,
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
    )

    direction    = Column(String(20))          # long / short / neutral / conditional
    entry_point  = Column(Float)
    entry_type   = Column(String(30))          # limit / market / breakout
    take_profits = Column(JSONB)               # [{"price": 48000, "label": "TP1"}, ...]
    stop_loss    = Column(Float)
    invalidation = Column(Text)
    confidence   = Column(Float)
    reasoning    = Column(Text)
    status       = Column(String(20), nullable=False, default="running")
    raw          = Column(JSONB)               # full original AI signal dict

    signal  = relationship("Signal", back_populates="scenarios")
    results = relationship(
        "ScenarioResult",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_scenarios_signal_id", "signal_id"),
        Index("ix_scenarios_status",    "status"),
    )


class ScenarioResult(Base):
    """
    Post-hoc evaluation of a Scenario's outcome.

    Populated by a separate evaluation job once the scenario's timeframe
    has expired or a TP/SL has been hit.
    """
    __tablename__ = "scenario_results"

    id          = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )

    result       = Column(String(20), nullable=False)  # success / failed / running / expired
    pnl_percent  = Column(Float)
    hit_tp       = Column(Float)        # price at which TP was hit (nullable)
    hit_sl       = Column(Float)        # price at which SL was hit (nullable)
    max_drawdown = Column(Float)
    evaluated_at = Column(DateTime)

    scenario = relationship("Scenario", back_populates="results")

    __table_args__ = (
        Index("ix_scenario_results_scenario_id", "scenario_id"),
    )
