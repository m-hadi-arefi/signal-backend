"""
Signal Evaluator — runs every POLL_INTERVAL seconds.

For every running Scenario it:
  1. Fetches the current price from Redis.
  2. Confirms whether the entry condition has been met (persisted in Redis).
  3. Tracks the best TP hit so far and price extremes (for drawdown).
  4. Writes a fresh snapshot to scenario_results via ON CONFLICT upsert.
  5. When a terminal condition is reached (SL / expire), finalises the result
     and updates scenarios.status.

Scenario lifecycle visible in the DB:
  scenarios.status  │  scenario_results.result  │  entered_at
  ──────────────────┼───────────────────────────┼────────────────
  running           │  running                  │  NULL          ← waiting for entry
  active            │  running                  │  <timestamp>   ← in play
  success           │  success                  │  <timestamp>   ← TP hit
  failed            │  failed                   │  <timestamp>   ← SL hit
  expired           │  expired                  │  NULL or ts    ← time ran out
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from core.logger import log
from core.redis import get_redis
from shared.database.session import SessionLocal

SERVICE_NAME    = "signal_evaluator"
POLL_INTERVAL   = 60           # seconds between full evaluation cycles
HEALTHCHECK_FILE = "/tmp/worker_ready"
REDIS_TTL       = 40 * 24 * 3600  # 40 days — safely covers the longest expire_time (1y)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_duration(expire_str: Optional[str]) -> timedelta:
    """'1d' → timedelta(days=1),  '2w' → timedelta(weeks=2), etc.  Default: 7 days."""
    if not expire_str or not isinstance(expire_str, str):
        return timedelta(days=7)
    s = expire_str.strip().lower()
    try:
        val  = int(s[:-1])
        unit = s[-1]
        if unit == "d": return timedelta(days=val)
        if unit == "w": return timedelta(weeks=val)
        if unit == "m": return timedelta(days=val * 30)
        if unit == "y": return timedelta(days=val * 365)
    except (ValueError, IndexError):
        pass
    return timedelta(days=7)


def _pnl(direction: str, entry: Optional[float], exit_price: float) -> Optional[float]:
    if not entry or entry == 0:
        return None
    if direction == "long":
        return round((exit_price - entry) / entry * 100, 4)
    if direction == "short":
        return round((entry - exit_price) / entry * 100, 4)
    return None


def _tp_prices(take_profits) -> list:
    """Return a flat list of float TP prices from the JSONB array."""
    out = []
    for tp in (take_profits or []):
        try:
            if isinstance(tp, dict):
                p = tp.get("price")
            elif isinstance(tp, (int, float)):
                p = tp
            else:
                continue
            if p is not None:
                out.append(float(p))
        except (TypeError, ValueError):
            pass
    return out


# ── Evaluator ──────────────────────────────────────────────────────────────────

class SignalEvaluator:

    def __init__(self):
        self.running = False
        self.redis   = get_redis()

    def signal_ready(self):
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
        except Exception as e:
            print(f"[{SERVICE_NAME}] healthcheck write failed: {e}")

    # ── Redis ──────────────────────────────────────────────────────────────────

    def _price(self, symbol: str) -> Optional[float]:
        try:
            v = self.redis.get(f"{symbol.lower()}usdt")
            return float(v) if v else None
        except Exception:
            return None

    def _confirm_entry(self, sc_id: int, direction: str,
                       entry_point: Optional[float], entry_type: Optional[str],
                       price: float) -> bool:
        """
        Returns True when the entry condition is met.
        Persists confirmation in Redis so subsequent cycles don't re-evaluate.
        Immediate/market entries are confirmed on the very first cycle and
        the flag is set so newly_entered stays True only once.
        """
        # Check Redis first — covers all previously confirmed scenarios
        if self.redis.exists(f"eval:entered:{sc_id}"):
            return True

        et = (entry_type or "").lower()
        if entry_point is None or et in ("market", "now"):
            # Immediate market entry — confirm right now
            self.redis.set(f"eval:entered:{sc_id}", "1", ex=REDIS_TTL)
            return True

        if   et == "break_up":   confirmed = price >= entry_point
        elif et == "break_down": confirmed = price <= entry_point
        elif direction == "long":  confirmed = price <= entry_point
        elif direction == "short": confirmed = price >= entry_point
        else:                      confirmed = True   # neutral / conditional

        if confirmed:
            self.redis.set(f"eval:entered:{sc_id}", "1", ex=REDIS_TTL)
        return confirmed

    def _track_extremes(self, sc_id: int, price: float):
        """Keep a running min/max price for max-drawdown calculation."""
        for key, fn in ((f"eval:min:{sc_id}", min), (f"eval:max:{sc_id}", max)):
            prev = self.redis.get(key)
            self.redis.set(key, str(fn(price, float(prev)) if prev else price), ex=REDIS_TTL)

    def _best_tp(self, sc_id: int, direction: str, tps: list, price: float) -> Optional[float]:
        """
        Return the best TP price hit across all cycles.
        Long  → highest TP price reached (price >= tp).
        Short → lowest  TP price reached (price <= tp).
        Progressive: once a TP is hit it stays recorded even if price reverses.
        """
        prices = _tp_prices(tps)
        if direction == "long":
            hit_now = [p for p in prices if price >= p]
            current  = max(hit_now) if hit_now else None
        elif direction == "short":
            hit_now = [p for p in prices if price <= p]
            current  = min(hit_now) if hit_now else None
        else:
            current = None

        stored = self.redis.get(f"eval:besttp:{sc_id}")
        prev   = float(stored) if stored else None

        if current is None:
            return prev
        if prev is None:
            best = current
        elif direction == "long":
            best = max(current, prev)
        else:
            best = min(current, prev)

        self.redis.set(f"eval:besttp:{sc_id}", str(best), ex=REDIS_TTL)
        return best

    def _drawdown(self, sc_id: int, direction: str, entry: Optional[float]) -> Optional[float]:
        if not entry or entry == 0:
            return None
        try:
            if direction == "long":
                v = self.redis.get(f"eval:min:{sc_id}")
                return round((float(v) - entry) / entry * 100, 4) if v else None
            if direction == "short":
                v = self.redis.get(f"eval:max:{sc_id}")
                return round((entry - float(v)) / entry * 100, 4) if v else None
        except (TypeError, ValueError):
            pass
        return None

    def _cleanup(self, sc_id: int):
        self.redis.delete(
            f"eval:entered:{sc_id}",
            f"eval:besttp:{sc_id}",
            f"eval:min:{sc_id}",
            f"eval:max:{sc_id}",
        )

    # ── Per-scenario evaluation (pure logic) ──────────────────────────────────

    def _eval(self, sc: dict, now: datetime) -> Optional[dict]:
        """
        Evaluate one scenario against the current market price.

        Returns a dict with two keys:
          - "row":    params for the scenario_results upsert
          - "status": new scenarios.status value (or None if unchanged)

        Returns None if the price is unavailable (skip this cycle).

        effective_entry:
          Scenarios with entry_point set → use it directly.
          Scenarios with entry_point=None (market/now) → use the market price
          that was snapshotted at signal creation time (Signal.current_market_price).
          This allows PnL and direction-based evaluation even for immediate entries.
        """
        sc_id      = sc["id"]
        direction  = sc["direction"] or "long"
        entry_pt   = sc["entry_point"]
        entry_type = sc["entry_type"]
        tps        = sc["take_profits"] or []
        sl         = sc["stop_loss"]
        raw        = sc["raw"] or {}
        expires_at = sc["signal_created_at"] + _parse_duration(raw.get("expire_time"))

        # Effective entry price: explicit level OR market price at signal creation
        signal_mkt = sc["signal_market_price"] or {}
        signal_price: Optional[float] = None
        try:
            if signal_mkt and signal_mkt.get("price"):
                signal_price = float(signal_mkt["price"])
        except (TypeError, ValueError):
            pass
        effective_entry: Optional[float] = entry_pt if entry_pt is not None else signal_price

        price = self._price(sc["symbol"])
        if price is None:
            return None

        # Whether this signal type has TPs / SL defined
        has_tps = bool(_tp_prices(tps))
        has_sl  = sl is not None

        # ── Entry state ───────────────────────────────────────────────────────
        # If this scenario is already "active" in the DB but the Redis key is
        # missing (e.g. after a Redis restart), restore it so we don't
        # mistakenly treat the scenario as "not yet entered" this cycle.
        redis_key = f"eval:entered:{sc_id}"
        if sc["sc_status"] == "active" and not self.redis.exists(redis_key):
            self.redis.set(redis_key, "1", ex=REDIS_TTL)

        was_entered   = bool(self.redis.exists(redis_key))
        is_entered    = self._confirm_entry(sc_id, direction, entry_pt, entry_type, price)
        newly_entered = is_entered and not was_entered

        # Track price extremes only once the position is open (accurate drawdown)
        if is_entered:
            self._track_extremes(sc_id, price)

        # Best TP hit so far — actively update only when entered and TPs exist;
        # otherwise read the last known value from Redis (could be None)
        if is_entered and has_tps:
            best_tp = self._best_tp(sc_id, direction, tps, price)
        else:
            stored  = self.redis.get(f"eval:besttp:{sc_id}")
            best_tp = float(stored) if stored else None

        # ── Determine terminal outcome ────────────────────────────────────────
        terminal     = None   # None | "success" | "failed" | "expired"
        hit_sl_price = None

        # SL check (only when entered and SL exists)
        if is_entered and has_sl and direction in ("long", "short"):
            sl_triggered = (direction == "long"  and price <= sl) or \
                           (direction == "short" and price >= sl)
            if sl_triggered:
                terminal     = "failed"
                hit_sl_price = sl

        # Expire check
        if terminal is None and now >= expires_at:
            if not is_entered:
                # Never triggered — time ran out
                terminal = "expired"
            elif best_tp is not None:
                # TP was hit at some point before expire
                terminal = "success"
            elif not has_tps and not has_sl and direction in ("long", "short"):
                # Pure directional signal (no TP / no SL defined) — evaluate
                # whether price moved in the right direction over the timeframe.
                if effective_entry is not None:
                    moved_right = (direction == "long"  and price > effective_entry) or \
                                  (direction == "short" and price < effective_entry)
                    terminal = "success" if moved_right else "failed"
                else:
                    terminal = "expired"   # no reference price available
            else:
                # Had TPs but none were hit, or direction is neutral/conditional
                terminal = "expired"

        is_terminal = terminal is not None

        # ── Compute P&L and drawdown (all use effective_entry) ───────────────
        if terminal == "success" and best_tp is not None:
            final_pnl = _pnl(direction, effective_entry, best_tp)
        elif terminal == "success":
            # Direction-based success: P&L vs current price at expire
            final_pnl = _pnl(direction, effective_entry, price)
        elif terminal == "failed":
            exit_px   = hit_sl_price if hit_sl_price is not None else price
            final_pnl = _pnl(direction, effective_entry, exit_px)
        elif is_entered:
            # Still running — live unrealised P&L
            final_pnl = _pnl(direction, effective_entry, price)
        else:
            final_pnl = None   # not entered yet

        drawdown = self._drawdown(sc_id, direction, effective_entry) if is_entered else None

        # ── Build result row ──────────────────────────────────────────────────
        result     = terminal or "running"
        entered_at = now if newly_entered else None   # COALESCE in SQL keeps first value

        row = {
            "sc_id":      sc_id,
            "result":     result,
            "pnl":        final_pnl,
            "hit_tp":     best_tp,       # best TP price hit so far
            "hit_sl":     hit_sl_price,  # null until SL triggered
            "drawdown":   drawdown,
            "entered_at": entered_at,
            "now":        now,
        }

        # ── Determine scenarios.status change ─────────────────────────────────
        if is_terminal:
            new_status = terminal          # success / failed / expired
            self._cleanup(sc_id)
        elif newly_entered:
            new_status = "active"          # entry confirmed → scenario is live
        else:
            new_status = None              # no change

        return {"row": row, "status": (sc_id, new_status) if new_status else None}

    # ── DB writes (batched) ────────────────────────────────────────────────────

    _UPSERT_SQL = text("""
        INSERT INTO scenario_results
            (scenario_id, result, pnl_percent, hit_tp, hit_sl, max_drawdown, entered_at, evaluated_at)
        VALUES
            (:sc_id, :result, :pnl, :hit_tp, :hit_sl, :drawdown, :entered_at, :now)
        ON CONFLICT (scenario_id) DO UPDATE SET
            result       = EXCLUDED.result,
            pnl_percent  = EXCLUDED.pnl_percent,
            hit_tp       = EXCLUDED.hit_tp,
            max_drawdown = EXCLUDED.max_drawdown,
            evaluated_at = EXCLUDED.evaluated_at,
            -- hit_sl and entered_at are set exactly once — never overwritten
            hit_sl     = COALESCE(scenario_results.hit_sl,     EXCLUDED.hit_sl),
            entered_at = COALESCE(scenario_results.entered_at, EXCLUDED.entered_at)
    """)

    async def _batch_write(self, rows: list, status_changes: list):
        """Persist all upserts and status updates in a single transaction."""
        async with SessionLocal() as session:
            # 1. Upsert scenario_results for every evaluated scenario
            await session.execute(self._UPSERT_SQL, rows)

            # 2. newly-entered scenarios: running → active
            to_active = [{"sc_id": sc_id}
                         for sc_id, s in status_changes if s == "active"]
            if to_active:
                await session.execute(text("""
                    UPDATE scenarios SET status = 'active'
                    WHERE  id = :sc_id AND status = 'running'
                """), to_active)

            # 3. terminal scenarios
            terminals = [{"sc_id": sc_id, "status": s}
                         for sc_id, s in status_changes if s != "active"]
            if terminals:
                await session.execute(text("""
                    UPDATE scenarios SET status = :status
                    WHERE  id = :sc_id
                    AND    status NOT IN ('success', 'failed', 'expired')
                """), terminals)

            await session.commit()

    # ── Main cycle ─────────────────────────────────────────────────────────────

    async def evaluate_cycle(self):
        # ── 1. Load all running scenarios ──
        async with SessionLocal() as session:
            try:
                rows = await session.execute(text("""
                    SELECT sc.id,
                           sc.status              AS sc_status,
                           sc.direction,
                           sc.entry_point,
                           sc.entry_type,
                           sc.take_profits,
                           sc.stop_loss,
                           sc.raw,
                           si.symbol,
                           si.created_at          AS signal_created_at,
                           si.current_market_price AS signal_market_price
                    FROM   scenarios sc
                    JOIN   signals   si ON sc.signal_id = si.id
                    WHERE  sc.status NOT IN ('success', 'failed', 'expired')
                """))
                scenarios = rows.mappings().all()
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "load_scenarios", error=e)
                return

        if not scenarios:
            return

        # ── 2. Evaluate each scenario (Redis I/O, pure logic) ──
        now            = datetime.utcnow()
        upsert_rows    = []
        status_changes = []
        skipped = errors = 0

        for sc in scenarios:
            try:
                result = self._eval(sc, now)
                if result is None:
                    skipped += 1
                    continue
                upsert_rows.append(result["row"])
                if result["status"]:
                    status_changes.append(result["status"])
            except Exception as e:
                log(SERVICE_NAME, "error", "-", f"eval_{sc['id']}", error=e)
                errors += 1

        # ── 3. Persist in one transaction ──
        if upsert_rows:
            try:
                await self._batch_write(upsert_rows, status_changes)
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "batch_write", error=e)
                return

        terminals = sum(1 for _, s in status_changes if s != "active")
        activated = sum(1 for _, s in status_changes if s == "active")
        log(SERVICE_NAME, "info", "-",
            f"cycle: {len(scenarios)} evaluated, {terminals} resolved, "
            f"{activated} activated, {skipped} skipped (no price), {errors} errors")

    # ── Run loop ───────────────────────────────────────────────────────────────

    async def run(self):
        print(f"[{SERVICE_NAME}] Starting — evaluating every {POLL_INTERVAL}s")
        self.running = True
        self.signal_ready()

        while self.running:
            try:
                await self.evaluate_cycle()
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "evaluate_cycle", error=e)
            await asyncio.sleep(POLL_INTERVAL)


async def main():
    evaluator = SignalEvaluator()
    await evaluator.run()


if __name__ == "__main__":
    asyncio.run(main())
