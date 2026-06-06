"""
Signal repository — inserts Signal + Scenario records from a validated event.

Design decisions:
  - One Signal per (trace_id, symbol) pair within a single event.
  - Multiple Scenarios per Signal (AI may return several trading hypotheses).
  - ScenarioResult rows are created by a separate evaluation job, never here.

v2 additions:
  - Direction inference from SL/TP geometry when direction field is missing/unknown.
  - TP sorting: ascending for long, descending for short.
  - TP geometric validation: remove TPs on wrong side of entry.
  - timeframe extraction and normalization.
  - expire_at computed at insert time from expire_time duration string.
  - correction_applied flag when normalization changed the AI output.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.signals import Scenario, Signal


_TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
    "1w": 604800, "1M": 2592000,
}

_DIRECTION_MAP = {
    "up":   "long",
    "down": "short",
    "buy":  "long",
    "sell": "short",
}

_DEFAULT_EXPIRE_DAYS = 7
_MAX_EXPIRE_DAYS     = 90
_MIN_EXPIRE_DAYS     = 1


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

        source_dict = _source_to_dict(event["source"])
        raw_text    = _extract_raw_text(event)
        ai_summary  = _extract_ai_summary(event)
        language    = _extract_language(event)
        analyzed_at = datetime.utcnow()

        inserted = 0
        for symbol, symbol_signals in groups.items():
            if not symbol_signals:
                continue

            market_price = price_by_symbol.get(symbol)

            # Top-level `props` from the event is stored on the Signal.
            # Any key not captured by the standard schema can live here.
            signal_props = event.get("props") or {}
            if not isinstance(signal_props, dict):
                signal_props = {}

            signal = Signal(
                symbol               = symbol,
                trace_id             = event["trace_id"],
                source               = source_dict,
                raw_text             = raw_text,
                ai_summary           = ai_summary,
                language             = language,
                current_market_price = market_price,
                analyzed_at          = analyzed_at,
                status               = "validated",
                props                = signal_props,
            )
            self.session.add(signal)
            await self.session.flush()

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

def _has_valid_entry(scenario: dict) -> bool:
    """Return True only if the scenario has a defined entry point (now or a number)."""
    entry = scenario.get("entry") or {}
    ep = (entry.get("price") if isinstance(entry, dict) else None) or \
         scenario.get("entry_point") or scenario.get("entry_price") or scenario.get("price")

    ep_type = (entry.get("type") if isinstance(entry, dict) else None) or \
              scenario.get("entry_point_type") or scenario.get("entry_type") or ""

    ep_str      = str(ep or "").strip().lower()
    ep_type_str = str(ep_type or "").strip().lower()

    if ep_str in ("now", "market") or ep_type_str in ("now", "market"):
        return True
    try:
        return float(str(ep or "").replace(",", "")) > 0
    except (ValueError, TypeError):
        return False


def _group_by_symbol(raw_signals: List[dict]) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue

        nested = raw.get("senarios") or raw.get("scenarios")
        if nested and isinstance(nested, list):
            symbol = str(raw.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            for scenario in nested:
                if isinstance(scenario, dict) and _has_valid_entry(scenario):
                    s = dict(scenario)
                    s["symbol"] = symbol
                    # Propagate top-level expire_time to scenario if not already set
                    if raw.get("expire_time") and "expire_time" not in s:
                        s["expire_time"] = raw["expire_time"]
                    # Propagate top-level timeframe
                    if raw.get("timeframe") and "timeframe" not in s:
                        s["timeframe"] = raw["timeframe"]
                    groups.setdefault(symbol, []).append(s)
            continue

        symbol = _extract_symbol(raw)
        if not symbol:
            continue
        if _has_valid_entry(raw):
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
    # ── Entry point ──────────────────────────────────────────────────────
    entry = raw.get("entry") or {}
    entry_point = _to_float(entry.get("price") if isinstance(entry, dict) else None)
    if entry_point is None:
        entry_point = _to_float(
            raw.get("entry_point") or raw.get("entry_price") or raw.get("price")
        )

    # ── Entry type ───────────────────────────────────────────────────────
    entry_type: Optional[str] = None
    if isinstance(entry, dict):
        entry_type = entry.get("type") or entry.get("entry_type")
    if not entry_type:
        entry_type = raw.get("entry_point_type") or raw.get("entry_type")
    if entry_type:
        entry_type = _normalize_entry_type(str(entry_type).lower())

    # Infer entry_type from entry_point when missing
    if not entry_type:
        ep_str = str(raw.get("entry_point") or raw.get("entry") or "").strip().lower()
        if ep_str in ("now", "market"):
            entry_type  = "market"
            entry_point = None
        elif entry_point is not None:
            entry_type = "fix"
        else:
            entry_type = "market"

    # ── Take-profits ─────────────────────────────────────────────────────
    targets_raw = raw.get("targets") or raw.get("tp") or raw.get("take_profits") or []
    take_profits: List[dict] = []
    for t in targets_raw:
        if isinstance(t, dict):
            p = _to_float(t.get("price"))
            if p is not None and p > 0:
                tp: dict = {"price": p}
                if t.get("label"):
                    tp["label"] = str(t["label"])
                take_profits.append(tp)
        else:
            p = _to_float(t)
            if p is not None and p > 0:
                take_profits.append({"price": p})

    # ── Stop-loss ────────────────────────────────────────────────────────
    sl_raw = raw.get("stop_loss") or raw.get("sl")
    stop_loss = _to_float(sl_raw.get("price") if isinstance(sl_raw, dict) else sl_raw)
    if stop_loss is not None and stop_loss <= 0:
        stop_loss = None

    # ── Direction ────────────────────────────────────────────────────────
    direction_raw = str(raw.get("direction") or raw.get("action") or "").lower().strip()
    direction = _DIRECTION_MAP.get(direction_raw, direction_raw) or None
    if direction not in ("long", "short", "neutral"):
        direction = None

    # Infer direction from geometry when missing
    correction_applied = False
    if not direction:
        direction = _infer_direction(entry_point, take_profits, stop_loss)
        if direction:
            correction_applied = True

    # ── Apply geometric fixes ────────────────────────────────────────────
    if direction and entry_point:
        take_profits, stop_loss, direction, correction_applied = _fix_geometry(
            entry_point, take_profits, stop_loss, direction, correction_applied
        )

    # ── Sort TPs ─────────────────────────────────────────────────────────
    if take_profits:
        if direction == "long":
            take_profits.sort(key=lambda t: t["price"])       # ascending
        elif direction == "short":
            take_profits.sort(key=lambda t: t["price"], reverse=True)  # descending

    # ── Timeframe ────────────────────────────────────────────────────────
    tf_raw = (
        raw.get("timeframe") or raw.get("time_frame") or
        raw.get("timeframe_label") or None
    )
    timeframe: Optional[str] = None
    if tf_raw:
        tf_clean = str(tf_raw).strip().lower().replace(" ", "")
        if tf_clean in _TF_SECONDS:
            timeframe = tf_clean
        # Fallback for common aliases
        elif tf_clean in ("1hour", "1h", "hour"):
            timeframe = "1h"
        elif tf_clean in ("4hour", "4h"):
            timeframe = "4h"
        elif tf_clean in ("daily", "1d", "day"):
            timeframe = "1d"
        elif tf_clean in ("weekly", "1w", "week"):
            timeframe = "1w"

    # Default timeframe for consolidation entries
    if timeframe is None and entry_type in ("consolidation_up", "consolidation_down"):
        timeframe = "1h"
    elif timeframe is None:
        timeframe = "4h"

    # ── Expire at ────────────────────────────────────────────────────────
    expire_str = (
        raw.get("expire_time") or raw.get("expiry") or
        raw.get("expiration") or None
    )
    expire_days = _parse_expire_days(expire_str)
    expire_at   = datetime.utcnow() + timedelta(days=expire_days)

    # ── Reasoning (text) ─────────────────────────────────────────────────
    conditions_list = raw.get("conditions") or []
    if not isinstance(conditions_list, list):
        conditions_list = []
    reasoning = "; ".join(str(c) for c in conditions_list if c) if conditions_list else None
    if not reasoning:
        reasoning = (
            raw.get("reasoning") or raw.get("rationale") or raw.get("reason") or None
        )

    # ── Invalidation ────────────────────────────────────────────────────
    invalidation = raw.get("invalidation") or raw.get("invalidation_scenario") or None
    if invalidation and not isinstance(invalidation, str):
        invalidation = str(invalidation)

    # ── Extended AI analysis fields ──────────────────────────────────────

    # price_type: "fixnumber" (exact levels) | "range" (approximate zone)
    price_type = str(raw.get("type") or raw.get("price_type") or "fixnumber").lower()
    if price_type not in ("fixnumber", "range"):
        price_type = "fixnumber"

    # intents: list of intent tags (entry_signal, target_prediction, …)
    intents = raw.get("intents") or []
    if not isinstance(intents, list):
        intents = []
    intents = [str(i) for i in intents if i]

    # sentiment: market mood for this scenario
    _SENTIMENTS = {"very_bullish", "bullish", "neutral", "bearish", "very_bearish", "conditional"}
    sentiment = str(raw.get("sentiment") or "").lower().strip() or None
    if sentiment and sentiment not in _SENTIMENTS:
        sentiment = None

    # urgency: how time-sensitive the signal is
    urgency = str(raw.get("urgency") or "").lower().strip() or None
    if urgency and urgency not in ("high", "medium", "low"):
        urgency = None

    # risk_level: assessed risk
    risk_level = str(raw.get("risk_level") or "").lower().strip() or None
    if risk_level and risk_level not in ("high", "medium", "low"):
        risk_level = None

    # leverage: numeric multiplier (null = not specified)
    leverage = _to_float(raw.get("leverage"))
    if leverage is not None and leverage <= 0:
        leverage = None

    # ambiguity_score: 0.0 (clear) → 1.0 (very ambiguous)
    ambiguity_score = _to_float(raw.get("ambiguity_score"))
    if ambiguity_score is not None:
        ambiguity_score = max(0.0, min(1.0, ambiguity_score))

    # possible_interpretations: alternative readings when ambiguous
    possible_interpretations = raw.get("possible_interpretations") or []
    if not isinstance(possible_interpretations, list):
        possible_interpretations = []

    # technical: {indicators, patterns, divergences, key_levels}
    technical = raw.get("technical")
    if technical is not None and not isinstance(technical, dict):
        technical = None

    # entities: {exchanges, wallets, whale_amounts, events, news, people, projects}
    entities = raw.get("entities")
    if entities is not None and not isinstance(entities, dict):
        entities = None

    # ── props: anything not captured by a dedicated column ───────────────
    _STANDARD_KEYS = {
        "symbol", "entry", "entry_point", "entry_price", "entry_point_type",
        "entry_type", "targets", "tp", "take_profits", "stop_loss", "sl",
        "direction", "action", "conditions", "reasoning", "rationale", "reason",
        "invalidation", "invalidation_scenario", "confidence", "expire_time",
        "expiry", "expiration", "timeframe", "time_frame", "timeframe_label",
        "type", "price_type", "senarios", "scenarios", "asset",
        # extended schema fields now stored as dedicated columns:
        "intents", "sentiment", "urgency", "risk_level", "leverage",
        "ambiguity_score", "possible_interpretations", "technical", "entities",
    }
    extra_props = {k: v for k, v in raw.items() if k not in _STANDARD_KEYS}

    return {
        "direction":                direction,
        "entry_point":              entry_point,
        "entry_type":               entry_type,
        "take_profits":             take_profits or None,
        "stop_loss":                stop_loss,
        "timeframe":                timeframe,
        "expire_at":                expire_at,
        "invalidation":             invalidation,
        "confidence":               _clamp(_to_float(raw.get("confidence"))),
        "reasoning":                reasoning,
        "status":                   "running",
        "correction_applied":       correction_applied,
        "raw":                      raw,
        # extended fields:
        "price_type":               price_type,
        "intents":                  intents,
        "conditions":               conditions_list,
        "sentiment":                sentiment,
        "urgency":                  urgency,
        "risk_level":               risk_level,
        "leverage":                 leverage,
        "ambiguity_score":          ambiguity_score,
        "possible_interpretations": possible_interpretations,
        "technical":                technical,
        "entities":                 entities,
        "props":                    extra_props,
    }


def _normalize_entry_type(et: str) -> str:
    """Normalise common typos and aliases for entry_type."""
    _map = {
        "condiention_up":   "consolidation_up",
        "condiention_down": "consolidation_down",
        "consolidation":    "consolidation_up",
        "breakout":         "break_up",
        "break":            "break_up",
        "limit":            "fix",
        "now":              "market",
        "immediate":        "market",
    }
    return _map.get(et, et)


def _infer_direction(
    entry_point: Optional[float],
    take_profits: List[dict],
    stop_loss: Optional[float],
) -> Optional[str]:
    """Infer long/short from SL and TP positions relative to entry."""
    votes: Dict[str, int] = {"long": 0, "short": 0}

    if stop_loss and entry_point:
        if stop_loss < entry_point:
            votes["long"] += 2      # SL below entry → likely long
        elif stop_loss > entry_point:
            votes["short"] += 2     # SL above entry → likely short

    if take_profits and entry_point:
        tp_prices = [t["price"] for t in take_profits if "price" in t]
        if tp_prices:
            avg_tp = sum(tp_prices) / len(tp_prices)
            if avg_tp > entry_point:
                votes["long"] += 1
            elif avg_tp < entry_point:
                votes["short"] += 1

    if votes["long"] > votes["short"]:
        return "long"
    if votes["short"] > votes["long"]:
        return "short"
    return None


def _fix_geometry(
    entry_point: float,
    take_profits: List[dict],
    stop_loss: Optional[float],
    direction: str,
    correction_applied: bool,
) -> tuple:
    """
    Remove TPs that are on the wrong side of entry for the given direction.
    Correct stop_loss if it's clearly inverted.
    """
    if direction == "long":
        # Remove TPs below or equal to entry
        filtered = [t for t in take_profits if t["price"] > entry_point]
        if len(filtered) != len(take_profits):
            take_profits       = filtered
            correction_applied = True

        # SL must be below entry for long — if not, note correction (don't auto-flip direction)
        if stop_loss is not None and stop_loss >= entry_point:
            stop_loss          = None   # discard invalid SL rather than silently wrong PnL
            correction_applied = True

    elif direction == "short":
        # Remove TPs above or equal to entry
        filtered = [t for t in take_profits if t["price"] < entry_point]
        if len(filtered) != len(take_profits):
            take_profits       = filtered
            correction_applied = True

        # SL must be above entry for short
        if stop_loss is not None and stop_loss <= entry_point:
            stop_loss          = None
            correction_applied = True

    return take_profits, stop_loss, direction, correction_applied


def _parse_expire_days(s: Optional[str]) -> int:
    if not s or not isinstance(s, str):
        return _DEFAULT_EXPIRE_DAYS
    s = s.strip().lower()
    try:
        val  = int(s[:-1])
        unit = s[-1]
        if unit == "d":
            days = val
        elif unit == "w":
            days = val * 7
        elif unit == "m":
            days = val * 30
        elif unit == "y":
            days = val * 365
        else:
            days = _DEFAULT_EXPIRE_DAYS
    except (ValueError, IndexError):
        days = _DEFAULT_EXPIRE_DAYS
    return max(_MIN_EXPIRE_DAYS, min(days, _MAX_EXPIRE_DAYS))


# ------------------------------------------------------------------ #
# Event field extraction helpers                                       #
# ------------------------------------------------------------------ #

def _source_to_dict(source) -> dict:
    if hasattr(source, "model_dump"):
        return source.model_dump(exclude_none=True)
    if isinstance(source, dict):
        return {k: v for k, v in source.items() if v is not None}
    return {}


def _extract_raw_text(event: dict) -> Optional[str]:
    payload = event.get("payload") or {}
    return payload.get("real_text") or payload.get("text") or None


def _extract_ai_summary(event: dict) -> Optional[str]:
    ai = event.get("ai_analysis") or {}
    if isinstance(ai, dict):
        return ai.get("summary") or ai.get("analysis_summary") or None
    return None


def _extract_language(event: dict) -> Optional[str]:
    """
    Extract the language of the original analysis.
    The Claude extended schema includes a top-level 'language' field: "en" | "fa" | "mixed".
    Falls back to ai_analysis.language if present.
    """
    _VALID = {"en", "fa", "mixed"}

    lang = event.get("language")
    if isinstance(lang, str) and lang.lower() in _VALID:
        return lang.lower()

    ai = event.get("ai_analysis") or {}
    if isinstance(ai, dict):
        lang = ai.get("language")
        if isinstance(lang, str) and lang.lower() in _VALID:
            return lang.lower()

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
