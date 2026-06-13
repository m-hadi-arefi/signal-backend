"""
FinalStoreWorker — terminal stage of the signal pipeline.

Responsibilities:
  1. Validate the incoming Kafka event (schema + required fields).
  2. For each unique symbol in the AI signal list:
       a. Snapshot the current market price from Redis (nullable — Redis miss ok).
       b. Create a Signal row + one Scenario row per AI scenario for that symbol.
  3. On validation failure: raise so BaseWorker dead-letters the event.
  4. Return None — this is the last step, nothing is forwarded to engine-signals.

Structured logging format: JSON lines via core.logger.log().
"""
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import ValidationError

from core.logger import log
from core.redis import get_redis
from core.worker import BaseWorker
from services.workers.final_store.repository import SignalRepository
from shared.database.session import SessionLocal
from shared.schemas.signal_payload import FinalEventSchema


class FinalStoreWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            service_name="final-store",
            topic="final-signals",
            group_id="final-group",
        )
        self.redis = get_redis()

    # ------------------------------------------------------------------ #
    # Core processing                                                      #
    # ------------------------------------------------------------------ #

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        trace_id = event.get("trace_id", "unknown")

        # 1. Schema validation — raises ValidationError → BaseWorker → DLQ
        try:
            validated = FinalEventSchema.model_validate(event)
        except ValidationError as exc:
            log(
                "final_store", "error", trace_id,
                "schema_validation_failed",
                event={"validation_errors": exc.errors()},
            )
            raise  # BaseWorker catches this and sends to dlq-signals

        raw_signals = validated.signals
        if not raw_signals:
            log("final_store", "info", trace_id, "no_signals_to_store")
            return None

        # Drop events where every symbol has an empty scenario list
        has_any_scenario = any(
            bool(s.get("senarios") or s.get("scenarios"))
            if isinstance(s, dict) and ("senarios" in s or "scenarios" in s)
            else True  # flat format — let repository decide
            for s in raw_signals
        )
        if not has_any_scenario:
            log("final_store", "info", trace_id, "no_scenarios_in_any_signal_dropped")
            return None

        # 2. Unique symbols — fetch Redis price for each
        symbols = _unique_symbols(raw_signals)
        price_by_symbol = await asyncio.to_thread(self._fetch_prices, symbols, trace_id)

        # 3. Persist Signal + Scenario records
        async with SessionLocal() as session:
            repo = SignalRepository(session)
            try:
                inserted = await repo.insert_signals_with_scenarios(
                    event=event,
                    price_by_symbol=price_by_symbol,
                )
                await session.commit()
                log(
                    "final_store", "info", trace_id,
                    "signals_stored",
                    event={"count": inserted, "symbols": list(symbols)},
                )
            except Exception:
                await repo.rollback()
                raise

        return None  # final step — nothing forwarded to engine-signals

    # ------------------------------------------------------------------ #
    # Redis price fetch (blocking I/O — run in thread)                    #
    # ------------------------------------------------------------------ #

    def _fetch_prices(
        self, symbols: set, trace_id: str
    ) -> Dict[str, Optional[dict]]:
        result: Dict[str, Optional[dict]] = {}
        for symbol in symbols:
            result[symbol] = self._get_market_price(symbol, trace_id)
        return result

    def _get_market_price(self, symbol: str, trace_id: str) -> Optional[dict]:
        sym_lower = symbol.lower()
        # Try USDT pair first, then IRT
        for suffix, label in (("usdt", f"redis:{sym_lower}usdt"),
                               ("irt",  f"redis:{sym_lower}irt")):
            try:
                raw = self.redis.get(f"{sym_lower}{suffix}")
                if raw is not None:
                    return {
                        "price":     float(raw),
                        "source":    label,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
            except Exception as exc:
                log(
                    "final_store", "warning", trace_id,
                    "redis_price_fetch_error",
                    event={"symbol": symbol, "key": f"{sym_lower}{suffix}"},
                    error=str(exc),
                )

        log(
            "final_store", "warning", trace_id,
            "market_price_unavailable",
            event={"symbol": symbol, "note": "storing NULL"},
        )
        return None


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _unique_symbols(raw_signals: list) -> set:
    """Extract deduplicated uppercase symbol names from the AI signal list."""
    symbols: set = set()
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        asset = raw.get("asset") or {}
        sym = (
            (asset.get("symbol") if isinstance(asset, dict) else None)
            or raw.get("symbol")
            or ""
        )
        sym = str(sym).upper().strip()
        if sym:
            symbols.add(sym)
    return symbols


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

async def run():
    worker = FinalStoreWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
