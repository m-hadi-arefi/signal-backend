"""
Signal Evaluator v3 — two-speed evaluation with candle-accurate TP/SL detection.

Active scenarios  (active=TRUE, status='running') : evaluated every FAST_INTERVAL (10s).
Waiting scenarios (active=FALSE, status='running'): evaluated every SLOW_INTERVAL (60s).

Key changes over v2:
  * scenarios.active column replaces status='active' as the entered-state flag.
    On entry:    scenarios.active=TRUE,  scenarios.status stays 'running'.
    On terminal: scenarios.active=FALSE, scenarios.status=<terminal>.
  * signals.active, signals.status, signals.active_scenarios_id updated on entry/terminal.
  * scenario_results.highest_price / lowest_price stored from Redis eval:max/min.
  * Progressive TP events: tp_hit emitted each time a NEW TP level is reached (not just at terminal).

Entry logic (entry_type from scenarios.entry_type):
  market / now        → immediate at current price
  break_up            → candle.high ≥ entry_point
  break_down          → candle.low  ≤ entry_point
  consolidation_up    → price holds ≥ entry for one full timeframe unit
  consolidation_down  → price holds ≤ entry for one full timeframe unit
  fix / limit / other → long: candle.low ≤ entry_point  short: candle.high ≥ entry_point
                         entry_price = entry_point (not market tick)

Exit logic:
  SL check first (pessimistic) unless TP was confirmed in a prior cycle.
  TP check uses candle.high for long, candle.low for short.
  Expiry: success if any TP was previously hit; otherwise 'expired'.

Multi-scenario rule:
  First scenario to enter sets sig:{signal_id}:active_sc via Redis SETNX.
  All other running siblings are immediately set to 'cancelled'.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from core.logger import log
from core.redis import get_redis
from shared.database.session import SessionLocal

SERVICE_NAME        = "signal_evaluator"
FAST_INTERVAL       = 10
SLOW_INTERVAL       = 60
SLOW_CYCLES         = SLOW_INTERVAL // FAST_INTERVAL
HEALTHCHECK_FILE    = "/tmp/worker_ready"
REDIS_TTL           = 40 * 24 * 3600
RANGE_TOLERANCE_PCT = 2.0
TICK_WINDOW         = 12   # seconds to look back when building pseudo-OHLC candle

TERMINAL_STATES = frozenset({
    "success", "failed", "expired", "cancelled", "invalid", "rejected", "skipped"
})

_TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
    "1w": 604800, "1M": 2592000,
}


# ── pure helpers ───────────────────────────────────────────────────────────────

def _parse_duration(s: Optional[str]) -> timedelta:
    if not s or not isinstance(s, str):
        return timedelta(days=7)
    s = s.strip().lower()
    try:
        val, unit = int(s[:-1]), s[-1]
        if unit == "d": return timedelta(days=val)
        if unit == "w": return timedelta(weeks=val)
        if unit == "m": return timedelta(days=val * 30)
        if unit == "y": return timedelta(days=val * 365)
    except (ValueError, IndexError):
        pass
    return timedelta(days=7)


def _tf_seconds(tf: Optional[str]) -> int:
    return _TF_SECONDS.get(tf or "", 3600)


def _tol(ref: float, price_type: str) -> float:
    return ref * RANGE_TOLERANCE_PCT / 100 if price_type == "range" else 0.0


def _pnl(direction: str, entry: float, exit_price: float) -> float:
    if direction == "long":
        return round((exit_price - entry) / entry * 100, 4)
    return round((entry - exit_price) / entry * 100, 4)


def _tp_prices(take_profits) -> list:
    out = []
    for tp in (take_profits or []):
        try:
            p = tp.get("price") if isinstance(tp, dict) else tp
            if p is not None:
                out.append(float(p))
        except (TypeError, ValueError):
            pass
    return out


# ── evaluator ─────────────────────────────────────────────────────────────────

class SignalEvaluator:

    def __init__(self):
        self.running = False
        self.redis   = get_redis()
        self._cycle  = 0

    def signal_ready(self):
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
        except Exception as e:
            print(f"[{SERVICE_NAME}] healthcheck write failed: {e}")

    # ── startup recovery ───────────────────────────────────────────────────────

    async def recover_redis_state(self):
        """
        Rebuild Redis tracking keys from DB for every entered scenario.
        Must be called once at startup before the evaluation loop begins.
        """
        log(SERVICE_NAME, "info", "-", "recovery: rebuilding Redis from DB")
        try:
            async with SessionLocal() as session:
                result = await session.execute(text("""
                    SELECT sc.id,
                           sc.signal_id,
                           sc.direction,
                           sc.take_profits,
                           sr.entry_price,
                           sr.hit_tp        AS hit_tp_price,
                           sr.hit_tp_index,
                           sr.evaluated_at,
                           sr.entered_at
                    FROM   scenarios sc
                    JOIN   scenario_results sr ON sr.scenario_id = sc.id
                    WHERE  sc.status = 'running' AND sc.active = TRUE
                """))
                rows = result.mappings().all()

                sc_ids = [r["id"] for r in rows]
                price_points_by_sc: dict = {}
                if sc_ids:
                    pp_result = await session.execute(text("""
                        SELECT scenario_id, recorded_at, price
                        FROM   scenario_price_points
                        WHERE  scenario_id = ANY(:ids)
                        ORDER  BY scenario_id, recorded_at ASC
                    """), {"ids": sc_ids})
                    for pp in pp_result.mappings().all():
                        price_points_by_sc.setdefault(pp["scenario_id"], []).append(pp)
        except Exception as e:
            log(SERVICE_NAME, "error", "-", "recovery: DB read failed", error=e)
            return

        if not rows:
            log(SERVICE_NAME, "info", "-", "recovery: no active scenarios — nothing to restore")
            return

        pipe = self.redis.pipeline()
        for sc in rows:
            sc_id = sc["id"]

            pipe.set(f"eval:entered:{sc_id}",            "1",         ex=REDIS_TTL)
            pipe.set(f"eval:first:{sc_id}",              "1",         ex=REDIS_TTL)
            pipe.set(f"sig:{sc['signal_id']}:active_sc", str(sc_id), ex=REDIS_TTL)

            if sc["entry_price"]:
                pipe.set(f"eval:entry_price:{sc_id}", str(sc["entry_price"]), ex=REDIS_TTL)

            if sc["hit_tp_price"]:
                pipe.set(f"eval:besttp:{sc_id}", str(sc["hit_tp_price"]), ex=REDIS_TTL)

            if sc["hit_tp_index"]:
                pipe.set(f"eval:besttp_idx:{sc_id}", str(sc["hit_tp_index"]), ex=REDIS_TTL)

            price_points = price_points_by_sc.get(sc_id, [])
            last_hist_epoch: Optional[float] = None

            if price_points:
                prices = [float(pp["price"]) for pp in price_points]
                pipe.set(f"eval:min:{sc_id}", str(min(prices)), ex=REDIS_TTL)
                pipe.set(f"eval:max:{sc_id}", str(max(prices)), ex=REDIS_TTL)

                # Restore timer from the last recorded point in scenario_price_points
                last_pt = price_points[-1]
                try:
                    recorded_at = last_pt["recorded_at"]
                    if hasattr(recorded_at, "timestamp"):
                        last_hist_epoch = recorded_at.timestamp()
                    else:
                        last_hist_epoch = datetime.fromisoformat(str(recorded_at)).timestamp()
                except (ValueError, AttributeError):
                    pass

            if last_hist_epoch is None:
                # No price history yet — use entered_at as the timer base so the
                # interval is measured correctly from when the scenario opened.
                # If entered_at is also missing, we leave eval:last_hist unset;
                # _history_point will save a point on the very next cycle.
                entered_at = sc.get("entered_at")
                if entered_at is not None:
                    try:
                        if hasattr(entered_at, "timestamp"):
                            last_hist_epoch = entered_at.timestamp()
                        else:
                            last_hist_epoch = datetime.fromisoformat(str(entered_at)).timestamp()
                    except (ValueError, AttributeError):
                        pass

            if last_hist_epoch is not None:
                pipe.set(f"eval:last_hist:{sc_id}", str(last_hist_epoch), ex=REDIS_TTL)

        pipe.execute()
        log(SERVICE_NAME, "info", "-", f"recovery: restored {len(rows)} active scenarios")

    # ── price / candle helpers ─────────────────────────────────────────────────

    def _candle(self, symbol: str) -> Optional[dict]:
        """
        Build pseudo-OHLC from the last TICK_WINDOW seconds of tick data.
        Falls back to the single last-price string key when tick buffer is empty.
        """
        sym = symbol.lower()
        try:
            now_ts = time.time()
            ticks  = self.redis.zrangebyscore(
                f"prices:{sym}:ticks",
                now_ts - TICK_WINDOW,
                "+inf",
                withscores=True,
            )
            if ticks:
                prices = [float(p) for p, _ in ticks]
                return {
                    "open":  prices[0],
                    "high":  max(prices),
                    "low":   min(prices),
                    "close": prices[-1],
                    "count": len(prices),
                }
        except Exception:
            pass

        try:
            v = self.redis.get(f"{sym}usdt")
            if v:
                p = float(v)
                return {"open": p, "high": p, "low": p, "close": p, "count": 1}
        except Exception:
            pass

        return None

    def _track_extremes(self, sc_id: int, candle: dict):
        """Update min/max using candle low and high for accurate drawdown tracking."""
        prev_min = self.redis.get(f"eval:min:{sc_id}")
        prev_max = self.redis.get(f"eval:max:{sc_id}")

        new_min = min(candle["low"],  float(prev_min)) if prev_min else candle["low"]
        new_max = max(candle["high"], float(prev_max)) if prev_max else candle["high"]

        self.redis.set(f"eval:min:{sc_id}", str(new_min), ex=REDIS_TTL)
        self.redis.set(f"eval:max:{sc_id}", str(new_max), ex=REDIS_TTL)

        return new_max, new_min

    def _best_tp(
        self,
        sc_id: int,
        direction: str,
        tps: list,
        candle: dict,
        price_type: str,
    ) -> tuple:
        """
        Return (best_tp_price, best_tp_index) using candle extremes.
        Also returns prev_tp_idx so caller can detect new TP hits this cycle.
        """
        prices = _tp_prices(tps)

        stored_p   = self.redis.get(f"eval:besttp:{sc_id}")
        stored_idx = int(self.redis.get(f"eval:besttp_idx:{sc_id}") or 0)

        if not prices:
            return (float(stored_p) if stored_p else None), stored_idx, stored_idx

        t           = _tol(candle["close"], price_type)
        check_price = candle["high"] if direction == "long" else candle["low"]

        if direction == "long":
            hit_idxs = [i + 1 for i, p in enumerate(prices) if check_price >= p - t]
        else:
            hit_idxs = [i + 1 for i, p in enumerate(prices) if check_price <= p + t]

        if not hit_idxs:
            return (float(stored_p) if stored_p else None), stored_idx, stored_idx

        current_best_idx   = max(hit_idxs)
        current_best_price = prices[current_best_idx - 1]

        prev_idx = stored_idx
        if current_best_idx > stored_idx:
            self.redis.set(f"eval:besttp:{sc_id}",     str(current_best_price), ex=REDIS_TTL)
            self.redis.set(f"eval:besttp_idx:{sc_id}", str(current_best_idx),   ex=REDIS_TTL)
            return current_best_price, current_best_idx, prev_idx

        return (float(stored_p) if stored_p else None), stored_idx, stored_idx

    def _drawdown(self, sc_id: int, direction: str, entry: float) -> Optional[float]:
        try:
            if direction == "long":
                v = self.redis.get(f"eval:min:{sc_id}")
                return round((float(v) - entry) / entry * 100, 4) if v else None
            v = self.redis.get(f"eval:max:{sc_id}")
            return round((entry - float(v)) / entry * 100, 4) if v else None
        except (TypeError, ValueError):
            return None

    def _max_favorable(self, sc_id: int, direction: str, entry: float) -> Optional[float]:
        try:
            if direction == "long":
                v = self.redis.get(f"eval:max:{sc_id}")
                return round((float(v) - entry) / entry * 100, 4) if v else None
            v = self.redis.get(f"eval:min:{sc_id}")
            return round((entry - float(v)) / entry * 100, 4) if v else None
        except (TypeError, ValueError):
            return None

    def _should_record_price(
        self,
        sc_id: int,
        timeframe: Optional[str],
        now: datetime,
        newly_entered: bool,
    ) -> bool:
        """
        Returns True when a price point should be inserted into scenario_price_points.

        Timer key: eval:last_hist:{sc_id} — stores the unix timestamp of the
        last recorded point.  Rebuilt by recover_redis_state() on startup.

        Interval: _tf_seconds(timeframe) — defaults to 3600 s (1 h) when no timeframe.
        If the key is missing (Redis restart / expiry), a point is emitted immediately
        so history never has a permanent blind-spot.
        """
        key = f"eval:last_hist:{sc_id}"

        if newly_entered:
            self.redis.set(key, str(now.timestamp()), ex=REDIS_TTL)
            return True

        stored = self.redis.get(key)
        if not stored:
            # Timer key lost — emit now and restart the clock from this moment.
            self.redis.set(key, str(now.timestamp()), ex=REDIS_TTL)
            return True

        if (now.timestamp() - float(stored)) >= _tf_seconds(timeframe):
            self.redis.set(key, str(now.timestamp()), ex=REDIS_TTL)
            return True

        return False

    def _cleanup(self, sc_id: int):
        self.redis.delete(
            f"eval:entered:{sc_id}",
            f"eval:entry_price:{sc_id}",
            f"eval:consol_start:{sc_id}",
            f"eval:last_hist:{sc_id}",
            f"eval:besttp:{sc_id}",
            f"eval:besttp_idx:{sc_id}",
            f"eval:min:{sc_id}",
            f"eval:max:{sc_id}",
            f"eval:first:{sc_id}",
            f"eval:data_gap_start:{sc_id}",
        )

    # ── data-gap tracking ──────────────────────────────────────────────────────

    def _note_data_gap(self, sc_id: int, now: datetime) -> bool:
        """
        Mark the start of a data gap for sc_id.
        Returns True if this is the FIRST gap notification (gap just opened),
        False if the gap was already open.
        """
        key = f"eval:data_gap_start:{sc_id}"
        if not self.redis.exists(key):
            self.redis.set(key, str(now.timestamp()), ex=7200)
            return True
        return False

    def _close_data_gap(self, sc_id: int, now: datetime) -> Optional[dict]:
        key      = f"eval:data_gap_start:{sc_id}"
        start_ts = self.redis.get(key)
        if start_ts:
            self.redis.delete(key)
            return {
                "from": datetime.fromtimestamp(float(start_ts)).isoformat(),
                "to":   now.isoformat(),
            }
        return None

    # ── entry confirmation ─────────────────────────────────────────────────────

    def _check_consolidation(
        self,
        sc_id: int,
        entry_point: float,
        side: str,
        tol: float,
        timeframe: Optional[str],
        price: float,
        now: datetime,
    ) -> bool:
        in_zone = (
            price >= entry_point - tol if side == "up"
            else price <= entry_point + tol
        )
        key = f"eval:consol_start:{sc_id}"

        if not in_zone:
            self.redis.delete(key)
            return False

        stored = self.redis.get(key)
        if not stored:
            self.redis.set(key, str(now.timestamp()), ex=REDIS_TTL)
            return False

        return (now.timestamp() - float(stored)) >= _tf_seconds(timeframe)

    def _confirm_entry(
        self,
        sc_id: int,
        direction: str,
        entry_point: Optional[float],
        entry_type: Optional[str],
        price_type: str,
        timeframe: Optional[str],
        candle: dict,
        now: datetime,
    ) -> tuple:
        entered_key = f"eval:entered:{sc_id}"
        if self.redis.exists(entered_key):
            return True, None

        et    = (entry_type or "").lower().strip()
        price = candle["close"]

        if entry_point is None or et in ("now", "market", ""):
            self.redis.set(entered_key, "1", ex=REDIS_TTL)
            return True, price

        t = _tol(entry_point, price_type)

        if et == "break_up":
            if candle["high"] >= entry_point - t:
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                return True, entry_point

        elif et == "break_down":
            if candle["low"] <= entry_point + t:
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                return True, entry_point

        elif et in ("consolidation_up", "condiention_up"):
            if self._check_consolidation(sc_id, entry_point, "up", t, timeframe, price, now):
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                self.redis.delete(f"eval:consol_start:{sc_id}")
                return True, price

        elif et in ("consolidation_down", "condiention_down"):
            if self._check_consolidation(sc_id, entry_point, "down", t, timeframe, price, now):
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                self.redis.delete(f"eval:consol_start:{sc_id}")
                return True, price

        else:
            # fix / limit — use candle low for long entry, candle high for short
            if direction == "long" and candle["low"] <= entry_point + t:
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                return True, entry_point
            if direction == "short" and candle["high"] >= entry_point - t:
                self.redis.set(entered_key, "1", ex=REDIS_TTL)
                return True, entry_point

        return False, None

    # ── per-scenario evaluation ────────────────────────────────────────────────

    def _eval(self, sc: dict, now: datetime, skip_entry: bool) -> Optional[dict]:
        """
        Evaluate one scenario for the current cycle.

        Returns None if price data is unavailable (skip this cycle).
        Returns a dict with keys: row, status, newly_entered, signal_id, dirty, events.
        """
        sc_id      = sc["id"]
        direction  = (sc["direction"] or "long").lower()
        entry_pt   = sc["entry_point"]
        entry_type = sc["entry_type"]
        tps        = sc["take_profits"] or []
        sl         = sc["stop_loss"]
        raw        = sc["raw"] or {}
        # price_type: prefer dedicated column (backfilled from raw on migration),
        # fall back to raw["type"] for rows inserted before the column existed.
        price_type = (sc.get("price_type") or raw.get("type") or "fixnumber").lower()
        timeframe  = sc.get("timeframe") or raw.get("timeframe")
        sc_active  = sc.get("sc_active", False)

        expires_at: datetime = sc.get("expire_at")
        if expires_at is None:
            expires_at = sc["signal_created_at"] + _parse_duration(raw.get("expire_time"))
        # Strip timezone info so comparison with naive `now` (UTC) never raises TypeError.
        if expires_at is not None and hasattr(expires_at, "tzinfo") and expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)

        candle = self._candle(sc["symbol"])
        if candle is None:
            return None

        closed_gap = self._close_data_gap(sc_id, now)

        price    = candle["close"]
        has_tps  = bool(_tp_prices(tps))
        has_sl   = sl is not None

        # Restore Redis entry flag from DB active column after restart
        entered_key = f"eval:entered:{sc_id}"
        if sc_active and not self.redis.exists(entered_key):
            self.redis.set(entered_key, "1", ex=REDIS_TTL)

        was_entered = bool(self.redis.exists(entered_key))

        # ── entry phase ──────────────────────────────────────────────────────
        if skip_entry and not was_entered:
            is_entered    = False
            confirmed_ep  = None
            newly_entered = False
        else:
            is_entered, confirmed_ep = self._confirm_entry(
                sc_id, direction, entry_pt, entry_type,
                price_type, timeframe, candle, now,
            )
            newly_entered = is_entered and not was_entered

        # Effective entry price
        effective_entry = None
        if newly_entered and confirmed_ep is not None:
            effective_entry = confirmed_ep
            self.redis.set(f"eval:entry_price:{sc_id}", str(effective_entry), ex=REDIS_TTL)
        elif is_entered:
            ep_r = self.redis.get(f"eval:entry_price:{sc_id}")
            if ep_r:
                effective_entry = float(ep_r)
            elif sc.get("existing_entry_price"):
                effective_entry = sc["existing_entry_price"]

        # Track price extremes and read absolute high/low
        highest_price = None
        lowest_price  = None
        if is_entered:
            high_abs, low_abs = self._track_extremes(sc_id, candle)
            highest_price = high_abs
            lowest_price  = low_abs

        # ── TP tracking (candle-accurate, progressive) ───────────────────────
        best_tp_price = None
        best_tp_idx   = 0
        prev_tp_idx   = 0
        if is_entered and has_tps:
            best_tp_price, best_tp_idx, prev_tp_idx = self._best_tp(
                sc_id, direction, tps, candle, price_type
            )
        elif is_entered:
            stored_p   = self.redis.get(f"eval:besttp:{sc_id}")
            stored_idx = self.redis.get(f"eval:besttp_idx:{sc_id}")
            best_tp_price = float(stored_p)   if stored_p   else None
            best_tp_idx   = int(stored_idx)   if stored_idx else 0
            prev_tp_idx   = best_tp_idx

        # ── terminal check ───────────────────────────────────────────────────
        terminal     = None
        hit_sl_price = None
        exit_price   = None

        if is_entered:
            if has_sl:
                sl_hit = (
                    (direction == "long"  and candle["low"]  <= sl) or
                    (direction == "short" and candle["high"] >= sl)
                )
                if sl_hit:
                    if best_tp_idx > 0:
                        terminal   = "success"
                        exit_price = best_tp_price
                    else:
                        terminal     = "failed"
                        hit_sl_price = sl
                        exit_price   = sl

            if terminal is None and has_tps and best_tp_idx > 0:
                terminal   = "success"
                exit_price = best_tp_price

        if terminal is None and now >= expires_at:
            if not is_entered:
                terminal = "expired"
            elif best_tp_idx > 0:
                terminal   = "success"
                exit_price = best_tp_price
            else:
                terminal   = "expired"
                exit_price = price

        is_terminal = terminal is not None

        # ── PnL calculations ─────────────────────────────────────────────────
        final_pnl     = None
        drawdown      = None
        max_favorable = None

        if effective_entry and effective_entry != 0:
            if terminal == "success":
                final_pnl = _pnl(direction, effective_entry, exit_price or price)
            elif terminal == "failed":
                final_pnl = _pnl(direction, effective_entry, hit_sl_price or price)
            elif terminal == "expired":
                final_pnl = _pnl(direction, effective_entry, price) if is_entered else None
            elif is_entered:
                final_pnl = _pnl(direction, effective_entry, price)

            if is_entered:
                drawdown      = self._drawdown(sc_id, direction, effective_entry)
                max_favorable = self._max_favorable(sc_id, direction, effective_entry)

        # ── price history ────────────────────────────────────────────────────
        # Decide whether to record a price point this cycle.
        # The point is written to scenario_price_points (a proper table row),
        # not appended to a JSONB blob.
        record_price = (
            self._should_record_price(sc_id, timeframe, now, newly_entered)
            if is_entered else False
        )

        result       = terminal or "running"
        entered_at   = now if newly_entered else None
        completed_at = now if is_terminal else None

        # ── dirty flag ───────────────────────────────────────────────────────
        dirty = is_terminal or newly_entered or record_price
        if is_entered and not is_terminal:
            dirty = True

        first_key = f"eval:first:{sc_id}"
        if not self.redis.exists(first_key):
            self.redis.set(first_key, "1", ex=REDIS_TTL)
            dirty = True

        # ── status / active transition ───────────────────────────────────────
        # "active" marker → set scenarios.active=TRUE (not a status change)
        # terminal  marker → set scenarios.status=<terminal>, active=FALSE
        if is_terminal:
            new_status = terminal
            new_active = False
            self._cleanup(sc_id)
        elif newly_entered:
            new_status = "active"   # used as marker → batch_write converts to active=TRUE
            new_active = True
        else:
            new_status = None
            new_active = None

        # ── events ───────────────────────────────────────────────────────────
        events = []

        # Persist any data-gap that just closed (price feed was restored)
        if closed_gap and is_entered:
            events.append({
                "sc_id":       sc_id,
                "event_type":  "data_gap_end",
                "price":       None,
                "event_data":  json.dumps(closed_gap),
                "occurred_at": now,
            })

        if newly_entered:
            events.append({
                "sc_id":       sc_id,
                "event_type":  "entered",
                "price":       effective_entry,
                "event_data":  None,
                "occurred_at": now,
            })

        # Progressive TP events: emit for each new TP level reached this cycle
        if is_entered and has_tps and best_tp_idx > prev_tp_idx:
            tp_prices_list = _tp_prices(tps)
            for i in range(prev_tp_idx, best_tp_idx):
                if i < len(tp_prices_list):
                    events.append({
                        "sc_id":       sc_id,
                        "event_type":  "tp_hit",
                        "price":       tp_prices_list[i],
                        "event_data":  json.dumps({"tp_index": i + 1}),
                        "occurred_at": now,
                    })

        if is_terminal:
            if terminal == "failed":
                events.append({
                    "sc_id":       sc_id,
                    "event_type":  "sl_hit",
                    "price":       hit_sl_price,
                    "event_data":  None,
                    "occurred_at": now,
                })
            events.append({
                "sc_id":       sc_id,
                "event_type":  "completed",
                "price":       exit_price,
                "event_data":  json.dumps({"result": terminal}),
                "occurred_at": now,
            })

        return {
            "row": {
                "sc_id":         sc_id,
                "result":        result,
                "pnl":           final_pnl,
                "hit_tp":        best_tp_price,
                "hit_tp_idx":    best_tp_idx if best_tp_idx > 0 else None,
                "hit_sl":        hit_sl_price,
                "drawdown":      drawdown,
                "max_favorable": max_favorable,
                "entered_at":    entered_at,
                "now":           now,
                "entry_price":   effective_entry if newly_entered else None,
                "exit_price":    exit_price,
                "completed_at":  completed_at,
                "highest_price": highest_price,
                "lowest_price":  lowest_price,
            },
            # Price point to INSERT into scenario_price_points (None = skip this cycle)
            "price_point": {
                "sc_id":      sc_id,
                "recorded_at": now,
                "price":      price,
                "pnl":        final_pnl,
            } if record_price else None,
            "status":        (sc_id, new_status) if new_status else None,
            "newly_entered": newly_entered,
            "signal_id":     sc["signal_id"],
            "is_terminal":   is_terminal,
            "dirty":         dirty,
            "events":        events,
        }

    # ── db writes ──────────────────────────────────────────────────────────────

    _UPSERT_SQL = text("""
        INSERT INTO scenario_results (
            scenario_id, result, pnl_percent, hit_tp, hit_tp_index, hit_sl,
            max_drawdown, max_favorable, entered_at, evaluated_at, entry_price,
            exit_price, completed_at, highest_price, lowest_price
        ) VALUES (
            :sc_id, :result, :pnl, :hit_tp, :hit_tp_idx, :hit_sl,
            :drawdown, :max_favorable, :entered_at, :now, :entry_price,
            :exit_price, :completed_at, :highest_price, :lowest_price
        )
        ON CONFLICT (scenario_id) DO UPDATE SET
            result        = EXCLUDED.result,
            pnl_percent   = EXCLUDED.pnl_percent,
            hit_tp        = EXCLUDED.hit_tp,
            hit_tp_index  = COALESCE(EXCLUDED.hit_tp_index,   scenario_results.hit_tp_index),
            max_drawdown  = EXCLUDED.max_drawdown,
            max_favorable = EXCLUDED.max_favorable,
            evaluated_at  = EXCLUDED.evaluated_at,
            hit_sl        = COALESCE(scenario_results.hit_sl,       EXCLUDED.hit_sl),
            entered_at    = COALESCE(scenario_results.entered_at,   EXCLUDED.entered_at),
            entry_price   = COALESCE(scenario_results.entry_price,  EXCLUDED.entry_price),
            exit_price    = COALESCE(scenario_results.exit_price,   EXCLUDED.exit_price),
            completed_at  = COALESCE(scenario_results.completed_at, EXCLUDED.completed_at),
            highest_price = CASE
                WHEN :highest_price IS NULL THEN scenario_results.highest_price
                ELSE GREATEST(COALESCE(scenario_results.highest_price, 0), :highest_price)
            END,
            lowest_price  = CASE
                WHEN :lowest_price IS NULL THEN scenario_results.lowest_price
                ELSE LEAST(COALESCE(scenario_results.lowest_price, 9e15), :lowest_price)
            END
    """)

    # INSERT one price point per timeframe interval into the dedicated table.
    # ON CONFLICT DO NOTHING handles rare duplicate timestamps (e.g. two rapid retries).
    _PRICE_POINT_SQL = text("""
        INSERT INTO scenario_price_points (scenario_id, recorded_at, price, pnl_percent)
        VALUES (:sc_id, :recorded_at, :price, :pnl)
        ON CONFLICT DO NOTHING
    """)

    _EVENTS_SQL = text("""
        INSERT INTO scenario_events (scenario_id, event_type, price, event_data, occurred_at)
        VALUES (:sc_id, :event_type, :price, CAST(:event_data AS jsonb), :occurred_at)
    """)

    async def _batch_write(
        self,
        rows: list,
        status_changes: list,
        sibling_cancel: list,
        all_events: list,
        price_points: list,
        signal_activations: list,
        signal_terminals: list,
        now: datetime,
    ):
        async with SessionLocal() as session:
            if rows:
                await session.execute(self._UPSERT_SQL, rows)

            if price_points:
                await session.execute(self._PRICE_POINT_SQL, price_points)

            # Scenario enters → set active=TRUE (status stays 'running')
            to_active = [{"sc_id": sc_id} for sc_id, s in status_changes if s == "active"]
            if to_active:
                await session.execute(text("""
                    UPDATE scenarios
                    SET    active = TRUE, updated_at = NOW()
                    WHERE  id = :sc_id AND status = 'running'
                """), to_active)

            # Signal activation updates
            if signal_activations:
                await session.execute(text("""
                    UPDATE signals
                    SET    active = TRUE,
                           status = 'running',
                           active_scenarios_id = :sc_id
                    WHERE  id = :signal_id
                """), signal_activations)

            # Scenario reaches terminal → set status, clear active
            terminals = [
                {"sc_id": sc_id, "status": s}
                for sc_id, s in status_changes if s != "active"
            ]
            if terminals:
                await session.execute(text("""
                    UPDATE scenarios
                    SET    status = :status, active = FALSE, updated_at = NOW()
                    WHERE  id = :sc_id
                    AND    status NOT IN (
                        'success','failed','expired','cancelled',
                        'invalid','rejected','skipped'
                    )
                """), terminals)

            # Clear signal.active when the active scenario terminates
            if signal_terminals:
                await session.execute(text("""
                    UPDATE signals
                    SET    active = FALSE
                    WHERE  id = :signal_id
                      AND  active_scenarios_id = :sc_id
                """), signal_terminals)

            # Sibling cancellation — only cancel non-entered (active=FALSE) scenarios
            if sibling_cancel:
                await session.execute(text("""
                    UPDATE scenarios
                    SET    status = 'cancelled', active = FALSE, updated_at = NOW()
                    WHERE  id = :sc_id AND status = 'running' AND active = FALSE
                """), [{"sc_id": sc_id} for sc_id in sibling_cancel])

                cancel_rows = [
                    {
                        "sc_id":         sc_id,
                        "result":        "cancelled",
                        "pnl":           None,
                        "hit_tp":        None,
                        "hit_tp_idx":    None,
                        "hit_sl":        None,
                        "drawdown":      None,
                        "max_favorable": None,
                        "entered_at":    None,
                        "now":           now,
                        "entry_price":   None,
                        "exit_price":    None,
                        "completed_at":  now,
                        "highest_price": None,
                        "lowest_price":  None,
                    }
                    for sc_id in sibling_cancel
                ]
                await session.execute(self._UPSERT_SQL, cancel_rows)

                for sc_id in sibling_cancel:
                    all_events.append({
                        "sc_id":       sc_id,
                        "event_type":  "cancelled",
                        "price":       None,
                        "event_data":  json.dumps({"reason": "sibling_entered"}),
                        "occurred_at": now,
                    })

            if all_events:
                await session.execute(self._EVENTS_SQL, all_events)

            await session.commit()

    # ── main cycle ─────────────────────────────────────────────────────────────

    async def evaluate_cycle(self):
        self._cycle += 1
        run_waiting = (self._cycle % SLOW_CYCLES == 0)

        # Fast cycle: only entered (active=TRUE) scenarios
        # Slow cycle: all running scenarios (entered + waiting)
        if run_waiting:
            status_filter = "sc.status = 'running'"
        else:
            status_filter = "sc.status = 'running' AND sc.active = TRUE"

        async with SessionLocal() as session:
            try:
                result = await session.execute(text(f"""
                    SELECT sc.id,
                           sc.signal_id,
                           sc.status               AS sc_status,
                           sc.active               AS sc_active,
                           sc.direction,
                           sc.entry_point,
                           sc.entry_type,
                           sc.price_type,
                           sc.take_profits,
                           sc.stop_loss,
                           sc.timeframe,
                           sc.expire_at,
                           sc.raw,
                           si.symbol,
                           si.created_at           AS signal_created_at,
                           si.current_market_price AS signal_market_price,
                           sr.entry_price          AS existing_entry_price
                    FROM   scenarios sc
                    JOIN   signals   si ON sc.signal_id = si.id
                    LEFT JOIN scenario_results sr ON sr.scenario_id = sc.id
                    WHERE  {status_filter}
                """))
                scenarios = result.mappings().all()
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "load_scenarios", error=e)
                return

        if not scenarios:
            if run_waiting:
                log(SERVICE_NAME, "info", "-",
                    f"cycle #{self._cycle} (full): no running scenarios found")
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Signals that already have an entered scenario this cycle
        active_signals = {
            sc["signal_id"] for sc in scenarios if sc["sc_active"]
        }

        upsert_rows        = []
        status_changes     = []
        all_events         = []
        price_points       = []
        signal_activations = []
        signal_terminals   = []
        newly_active       = set()
        activated_sc_ids   = set()
        skipped = errors   = 0

        for sc in scenarios:
            try:
                sig_id     = sc["signal_id"]
                skip_entry = (sig_id in active_signals) or (sig_id in newly_active)

                res = self._eval(sc, now, skip_entry)
                if res is None:
                    skipped += 1
                    # Emit data_gap_start only when the scenario is already entered
                    # and this is the FIRST missing cycle (gap just opened).
                    if sc.get("sc_active"):
                        gap_opened = self._note_data_gap(sc["id"], now)
                        if gap_opened:
                            all_events.append({
                                "sc_id":       sc["id"],
                                "event_type":  "data_gap_start",
                                "price":       None,
                                "event_data":  None,
                                "occurred_at": now,
                            })
                    continue

                if res["dirty"]:
                    upsert_rows.append(res["row"])
                if res["status"]:
                    status_changes.append(res["status"])
                if res.get("events"):
                    all_events.extend(res["events"])
                if res.get("price_point"):
                    price_points.append(res["price_point"])

                if res["newly_entered"]:
                    newly_active.add(sig_id)
                    active_signals.add(sig_id)
                    activated_sc_ids.add(sc["id"])
                    signal_activations.append({
                        "sc_id":     sc["id"],
                        "signal_id": sig_id,
                    })

                # A scenario terminates the signal's active state when either:
                # (a) it was already the active scenario in DB (sc_active=TRUE), or
                # (b) it just entered AND terminated in the same cycle (market order → instant SL/TP).
                #     In that case sc_active is still FALSE in DB but signal_activations will
                #     set active=TRUE — we need to immediately clear it.
                if res["is_terminal"] and (sc["sc_active"] or res["newly_entered"]):
                    signal_terminals.append({
                        "sc_id":     sc["id"],
                        "signal_id": sig_id,
                    })

            except Exception as e:
                log(SERVICE_NAME, "error", "-", f"eval_{sc['id']}", error=e)
                errors += 1

        sibling_cancel = []
        if newly_active:
            for sc in scenarios:
                if (
                    sc["signal_id"] in newly_active
                    and sc["id"] not in activated_sc_ids
                    and sc["sc_status"] == "running"
                    and not sc["sc_active"]
                ):
                    sibling_cancel.append(sc["id"])
                    self._cleanup(sc["id"])

        if upsert_rows or sibling_cancel or all_events or price_points or signal_activations or signal_terminals:
            try:
                await self._batch_write(
                    upsert_rows, status_changes, sibling_cancel, all_events,
                    price_points, signal_activations, signal_terminals, now
                )
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "batch_write", error=e)
                return

        terminals = sum(1 for _, s in status_changes if s != "active")
        activated = sum(1 for _, s in status_changes if s == "active")
        if terminals or activated or sibling_cancel or errors or skipped or upsert_rows:
            log(
                SERVICE_NAME, "info", "-",
                f"cycle #{self._cycle} ({'full' if run_waiting else 'fast'}): "
                f"{len(scenarios)} checked, {len(upsert_rows)} written, "
                f"{terminals} resolved, {activated} activated, "
                f"{len(sibling_cancel)} cancelled, "
                f"{len(all_events)} events, "
                f"{skipped} no-price, {errors} errors",
            )

    # ── run loop ───────────────────────────────────────────────────────────────

    async def run(self):
        print(
            f"[{SERVICE_NAME}] Starting v3 — "
            f"active: every {FAST_INTERVAL}s, "
            f"waiting: every {SLOW_INTERVAL}s"
        )
        self.running = True
        self.signal_ready()

        while self.running:
            try:
                await self.evaluate_cycle()
            except Exception as e:
                log(SERVICE_NAME, "error", "-", "evaluate_cycle", error=e)
            await asyncio.sleep(FAST_INTERVAL)


async def main():
    evaluator = SignalEvaluator()
    await evaluator.recover_redis_state()
    await evaluator.run()


if __name__ == "__main__":
    asyncio.run(main())
