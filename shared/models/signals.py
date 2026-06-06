from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
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
    # Shape: {price: float, source: str, timestamp: str}
    current_market_price = Column(JSONB)

    # Signal lifecycle status
    # pending → analyzing → validated → completed  (normal path)
    # pending → analyzing → invalid / rejected     (failure path)
    status           = Column(String(20), nullable=False, default="validated")
    validation_error = Column(Text)

    # Set to TRUE when one of this signal's scenarios enters a position.
    # active_scenarios_id points to the scenario that is currently active.
    active              = Column(Boolean, nullable=False, default=False)
    active_scenarios_id = Column(Integer, ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True)

    # Language of the original analysis message: "en" | "fa" | "mixed"
    language = Column(String(10))

    # Extensible bucket for additional metadata that doesn't fit the standard schema.
    # Store anything extra here to avoid breaking other services with schema changes.
    props = Column(JSONB, default=dict)

    created_at   = Column(DateTime, nullable=False, default=datetime.utcnow)
    analyzed_at  = Column(DateTime)
    completed_at = Column(DateTime)

    scenarios = relationship(
        "Scenario",
        back_populates="signal",
        cascade="all, delete-orphan",
        lazy="select",
        foreign_keys="[Scenario.signal_id]",
    )

    __table_args__ = (
        Index("ix_signals_symbol",         "symbol"),
        Index("ix_signals_trace_id",       "trace_id"),
        Index("ix_signals_created_at",     "created_at"),
        Index("ix_signals_symbol_created", "symbol", "created_at"),
        Index("ix_signals_source_gin",     "source", postgresql_using="gin"),
    )


class Scenario(Base):
    """
    One tradeable scenario within a Signal.

    Fields mirror what the AI extracts: entry, targets, stop, confidence,
    reasoning, and the current lifecycle status.

    Status transitions (strict):
      pending  → running | invalid | rejected
      running  → active | cancelled | expired | invalid
      active   → success | failed | expired

    Terminal states (immutable once set):
      success | failed | expired | cancelled | invalid | rejected | skipped
    """
    __tablename__ = "scenarios"

    id        = Column(Integer, primary_key=True)
    signal_id = Column(
        Integer,
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
    )

    direction    = Column(String(20))          # long / short / neutral
    entry_point  = Column(Float)
    entry_type   = Column(String(30))          # market / fix / break_up / break_down / consolidation_*
    take_profits = Column(JSONB)               # [{"price": 48000, "label": "TP1"}, ...]
    stop_loss    = Column(Float)
    timeframe    = Column(String(10))          # 1m / 5m / 15m / 1h / 4h / 1d etc.
    expire_at    = Column(DateTime)            # computed at insert: created_at + expire_time duration
    invalidation = Column(Text)
    confidence   = Column(Float)
    reasoning    = Column(Text)

    # Status lifecycle (see docstring above)
    status = Column(String(20), nullable=False, default="running")

    # TRUE when this scenario has entered a position (evaluator set it).
    # On terminal: reset to FALSE, status set to the terminal state.
    active = Column(Boolean, nullable=False, default=False)

    correction_applied = Column(Boolean, default=False)
    raw                = Column(JSONB)         # full original AI signal dict

    # ── AI analysis fields (from Claude extended schema) ──────────────────────

    # Price precision type: "fixnumber" (exact levels) | "range" (approximate zone)
    price_type = Column(String(20))

    # Intent tags, e.g. ["entry_signal", "target_prediction", "conditional_scenario"]
    intents = Column(JSONB, default=list)

    # Conditions that must be met for this scenario to activate, e.g.
    # ["4h candle closes above EMA", "volume > 1.5x average"]
    conditions = Column(JSONB, default=list)

    # Market sentiment for this scenario
    # very_bullish | bullish | neutral | bearish | very_bearish | conditional
    sentiment = Column(String(20))

    # How urgently this signal should be acted on: high | medium | low
    urgency = Column(String(10))

    # Assessed risk level: high | medium | low
    risk_level = Column(String(10))

    # Leverage multiplier, if mentioned (e.g. 10 for 10x). NULL = not specified.
    leverage = Column(Float)

    # AI's self-assessed confidence in the parse quality (0.0–1.0)
    ambiguity_score = Column(Float)

    # Alternative readings when the signal is ambiguous (ambiguity_score > 0.4)
    possible_interpretations = Column(JSONB, default=list)

    # Technical analysis details: {indicators, patterns, divergences, key_levels}
    technical = Column(JSONB)

    # Named entities extracted from text:
    # {exchanges, wallets, whale_amounts, events, news, people, projects}
    entities = Column(JSONB)

    # Extensible bucket for additional metadata that doesn't fit the standard schema.
    # Store anything extra here (e.g. custom AI fields, frontend hints) without
    # touching other services' schemas.
    props = Column(JSONB, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal  = relationship(
        "Signal",
        back_populates="scenarios",
        foreign_keys="[Scenario.signal_id]",
    )
    results = relationship(
        "ScenarioResult",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="select",
    )
    events = relationship(
        "ScenarioEvent",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="select",
    )
    price_points = relationship(
        "ScenarioPricePoint",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ScenarioPricePoint.recorded_at",
    )

    __table_args__ = (
        Index("ix_scenarios_signal_id", "signal_id"),
        Index("ix_scenarios_status",    "status"),
    )


class ScenarioResult(Base):
    """
    Live and final evaluation state for a Scenario.

    Populated by the evaluator every 10–60 seconds.
    One row per scenario (UNIQUE constraint on scenario_id).

    result lifecycle:
      "running"   → being evaluated (entered_at NULL = waiting; NOT NULL = active)
      "success"   → at least TP1 hit
      "failed"    → SL hit
      "expired"   → time limit reached without TP/SL
      "cancelled" → sibling scenario entered first
    """
    __tablename__ = "scenario_results"

    id          = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )

    result        = Column(String(20), nullable=False)
    pnl_percent   = Column(Float)      # live unrealized PnL; final PnL when terminal
    hit_tp        = Column(Float)      # best TP price touched (progressive)
    hit_tp_index  = Column(Integer)    # ordinal of best TP hit: 1 = TP1, 2 = TP2 …
    hit_sl        = Column(Float)      # SL price at trigger; set once
    max_drawdown  = Column(Float)      # worst PnL seen since entry (negative = loss)
    max_favorable = Column(Float)      # best PnL seen since entry (positive = gain)

    entered_at   = Column(DateTime)    # when entry condition confirmed; NULL = not entered
    evaluated_at = Column(DateTime)    # timestamp of last evaluation cycle
    completed_at = Column(DateTime)    # timestamp of terminal state

    entry_price  = Column(Float)       # market/limit price at entry confirmation
    exit_price   = Column(Float)       # price at which position closed (TP, SL, or expiry close)

    # Absolute highest and lowest prices seen since entry (raw price, not % PnL).
    # Used by the API to compute price-range performance without extra Redis lookups.
    highest_price = Column(Float)
    lowest_price  = Column(Float)

    # price_history column removed — data is now in scenario_price_points table.
    # data_gaps column kept for backward-compat but populated via scenario_events.
    data_gaps = Column(JSONB, default=list)

    scenario = relationship("Scenario", back_populates="results")

    __table_args__ = (
        UniqueConstraint("scenario_id", name="uq_scenario_results_scenario_id"),
        Index("ix_scenario_results_scenario_id", "scenario_id"),
    )


class ScenarioEvent(Base):
    """
    Append-only audit log for every state transition in a Scenario.

    event_type values:
      entered | tp_hit | sl_hit | expired | completed |
      cancelled | invalid | rejected | data_gap_start | data_gap_end
    """
    __tablename__ = "scenario_events"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type  = Column(String(30), nullable=False)
    price       = Column(Float)
    event_data  = Column(JSONB)          # renamed from 'metadata' (reserved by SQLAlchemy)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    scenario = relationship("Scenario", back_populates="events")

    __table_args__ = (
        Index("ix_scenario_events_sc_ts", "scenario_id", "occurred_at"),
        Index("ix_scenario_events_type",  "event_type",  "occurred_at"),
    )


class ScenarioPricePoint(Base):
    """
    One price snapshot for an active scenario, recorded once per timeframe unit.

    Replaces the old scenario_results.price_history JSONB blob.
    Each row is an immutable, append-only record — never updated after INSERT.

    Interval rules (enforced by the evaluator):
      - First point at entry time (newly_entered=True)
      - Subsequent points every _tf_seconds(timeframe):
          1m→60s  5m→300s  15m→900s  1h→3600s  4h→14400s  1d→86400s
          default (no timeframe) → 3600s (1 hour)
    """
    __tablename__ = "scenario_price_points"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    recorded_at = Column(DateTime, nullable=False)
    price       = Column(Float, nullable=False)
    pnl_percent = Column(Float)   # live PnL at the moment this point was recorded

    scenario = relationship("Scenario", back_populates="price_points")

    __table_args__ = (
        Index("ix_scenario_pp_sc_ts", "scenario_id", "recorded_at"),
    )
