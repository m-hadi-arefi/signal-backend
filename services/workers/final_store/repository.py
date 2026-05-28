"""
Signal repository — inserts Signal + Scenario records from a validated event.

Design decisions:
  - One Signal per (trace_id, symbol) pair within a single event.
  - Multiple Scenarios per Signal (AI may return several trading hypotheses).
  - ScenarioResult rows are created by a separate evaluation job, never here.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.signals import Scenario, Signal


class SignalRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def insert_signals_with_scenarios(
        self,
        event: dict,
        price_by_symbol: Dict[str, Optional[dict]],
    ) -> int:
        """
        Group raw AI signals by symbol, create one Signal + N Scenarios each.

        Args:
            event: validated Kafka event dict (has trace_id, source, signals, …)
            price_by_symbol: {SYMBOL: market_price_snapshot or None}

        Returns:
            number of Signal records inserted
        """
        raw_signals: List[dict] = event.get("signals") or []
        if not raw_signals:
            return 0

        groups = _group_by_symbol(raw_signals)
        if not groups:
            return 0

        source_dict  = _source_to_dict(event["source"])
        raw_text     = _extract_raw_text(event)
        ai_summary   = _extract_ai_summary(event)
        analyzed_at  = datetime.utcnow()

        inserted = 0
        for symbol, symbol_signals in groups.items():
            market_price = price_by_symbol.get(symbol)

            signal = Signal(
                symbol               = symbol,
                trace_id             = event["trace_id"],
                source               = source_dict,
                raw_text             = raw_text,
                ai_summary           = ai_summary,
                current_market_price = market_price,
                analyzed_at          = analyzed_at,
            )
            self.session.add(signal)
            await self.session.flush()  # populate signal.id before adding scenarios

            for raw in symbol_signals:
                scenario_data = _normalize_scenario(raw)
                self.session.add(Scenario(signal_id=signal.id, **scenario_data))

            inserted += 1

        return inserted

    async def rollback(self):
        await self.session.rollback()


# ------------------------------------------------------------------ #
# Grouping helpers                                                     #
# ------------------------------------------------------------------ #

def _group_by_symbol(raw_signals: List[dict]) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        symbol = _extract_symbol(raw)
        if not symbol:
            continue
        groups.setdefault(symbol, []).append(raw)
    return groups


def _extract_symbol(raw: dict) -> Optional[str]:
    asset = raw.get("asset") or {}
    sym = (
        (asset.get("symbol") if isinstance(asset, dict) else None)
        or raw.get("symbol")
        or ""
    )
    return str(sym).upper().strip() or None


# ------------------------------------------------------------------ #
# Scenario normalisation                                               #
# ------------------------------------------------------------------ #

def _normalize_scenario(raw: dict) -> dict:
    # Entry point
    entry = raw.get("entry") or {}
    entry_point = _to_float(entry.get("price") if isinstance(entry, dict) else None)
    if entry_point is None:
        entry_point = _to_float(raw.get("entry_price") or raw.get("price"))

    # Entry type (e.g. "limit", "market", "breakout")
    entry_type: Optional[str] = None
    if isinstance(entry, dict):
        entry_type = entry.get("type") or entry.get("entry_type")
    if entry_type:
        entry_type = str(entry_type).lower()

    # Take-profit levels — normalised to [{price, label?}, ...]
    targets = raw.get("targets") or []
    take_profits: List[dict] = []
    for t in targets:
        if isinstance(t, dict):
            p = _to_float(t.get("price"))
            if p is not None:
                tp: dict = {"price": p}
                if t.get("label"):
                    tp["label"] = str(t["label"])
                take_profits.append(tp)
        else:
            p = _to_float(t)
            if p is not None:
                take_profits.append({"price": p})

    # Stop-loss
    sl = raw.get("stop_loss") or {}
    stop_loss = _to_float(sl.get("price") if isinstance(sl, dict) else sl)

    # Direction — keep as-is (long / short / neutral / conditional)
    direction = str(raw.get("direction") or raw.get("action") or "").lower().strip() or None

    # Conditions → reasoning prose
    conditions = raw.get("conditions") or []
    reasoning = "; ".join(str(c) for c in conditions if c) if conditions else None
    if not reasoning:
        reasoning = raw.get("reasoning") or raw.get("rationale") or None

    # Invalidation scenario description
    invalidation = raw.get("invalidation") or raw.get("invalidation_scenario") or None
    if invalidation and not isinstance(invalidation, str):
        invalidation = str(invalidation)

    return {
        "direction":    direction,
        "entry_point":  entry_point,
        "entry_type":   entry_type,
        "take_profits": take_profits or None,
        "stop_loss":    stop_loss,
        "invalidation": invalidation,
        "confidence":   _clamp(_to_float(raw.get("confidence"))),
        "reasoning":    reasoning,
        "status":       "running",
        "raw":          raw,
    }


# ------------------------------------------------------------------ #
# Event field extraction helpers                                       #
# ------------------------------------------------------------------ #

def _source_to_dict(source) -> dict:
    """Convert SourceMetadata (Pydantic model or plain dict) to a dict for JSONB."""
    if hasattr(source, "model_dump"):
        return source.model_dump(exclude_none=True)
    if isinstance(source, dict):
        return {k: v for k, v in source.items() if v is not None}
    return {}


def _extract_raw_text(event: dict) -> Optional[str]:
    payload = event.get("payload") or {}
    # real_text is the pre-cleanup original; fall back to cleaned text
    return payload.get("real_text") or payload.get("text") or None


def _extract_ai_summary(event: dict) -> Optional[str]:
    ai = event.get("ai_analysis") or {}
    if isinstance(ai, dict):
        return ai.get("summary") or ai.get("analysis_summary") or None
    return None


# ------------------------------------------------------------------ #
# Value coercion helpers                                               #
# ------------------------------------------------------------------ #

def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, min(1.0, value))
