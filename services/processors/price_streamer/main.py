"""
Price Streamer — unified real-time price service.

USDT prices  : Binance WebSocket (miniTicker, ~1s per symbol)
               → fallback: MEXC WebSocket (all-tickers stream)
               → last-resort: Binance REST poll every REST_POLL seconds
IRT prices   : Nobitex REST poll every NOBITEX_POLL seconds
               Prices stored in Tomans (Nobitex returns Rials; divide by 10)

Redis keys
  {symbol}usdt            e.g. "btcusdt"  = "49853.21"   (last USDT price, TTL 90s)
  {symbol}irt             e.g. "btcirt"   = "3390000000" (IRT/Toman price, TTL 180s)
  prices:{symbol}:ticks   e.g. ZSET: score=unix_ts, member=price_str
                          Evaluator reads this for candle-accurate TP/SL detection.
                          Trimmed to last 60 s; TTL 90 s.

MEXC heartbeat note:
  MEXC sends {"ping": <ts>} JSON messages every ~30s.
  We must reply {"pong": <ts>} or the server closes the connection.
  websockets library ping is disabled (ping_interval=None) because MEXC
  does not respond to protocol-level WebSocket pings.
"""
import asyncio
import json
import time

import requests
import websockets
from sqlalchemy import text

from core.logger import log
from core.redis import get_redis
from shared.database.session import SessionLocal

SERVICE_NAME     = "price_streamer"
HEALTHCHECK_FILE = "/tmp/worker_ready"

# USDT WebSocket settings
USDT_TTL       = 90    # Redis TTL for USDT price string (s)
TICK_TTL       = 90    # Redis TTL for tick ZSET (s)
TICK_WINDOW    = 60    # keep only last N seconds in ZSET
RESUB_INTERVAL = 300   # re-subscribe to pick up new symbols
RECONNECT_WAIT = 5

# Nobitex REST settings
IRT_TTL      = 180
NOBITEX_POLL = 60

# Binance REST fallback settings (runs in parallel with WS — keeps prices fresh when WS is down)
REST_POLL = 30

_BINANCE_WS   = "wss://stream.binance.com:9443/stream"
_MEXC_WS      = "wss://wbs.mexc.com/ws"
_BINANCE_REST = "https://api.binance.com/api/v3/ticker/price"
_NOBITEX_URL  = "https://api.nobitex.ir/market/stats"

_SKIP = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}


class PriceStreamer:

    def __init__(self):
        self.redis   = get_redis()
        self.symbols: set = set()
        self.running = False

    def signal_ready(self):
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
        except Exception:
            pass

    # ── Shared: symbol list ────────────────────────────────────────────────────

    async def _load_symbols(self) -> set:
        try:
            async with SessionLocal() as session:
                rows = await session.execute(
                    text("SELECT symbol FROM tracked_coins WHERE is_active = TRUE")
                )
                return {
                    r[0].lower() for r in rows
                    if r[0].upper() not in _SKIP
                }
        except Exception as e:
            log(SERVICE_NAME, "error", "-", f"load_symbols ({type(e).__name__}: {e})")
            return set()

    # ── Price publish helpers ──────────────────────────────────────────────────

    def _publish_usdt(self, sym: str, price: str) -> None:
        """
        Store the latest USDT price two ways:
          1. Simple string key  ({sym}usdt)          — backward-compat, fast reads
          2. Sorted-set tick buffer (prices:{sym}:ticks) — OHLC candles in evaluator
        """
        now_ts   = time.time()
        key_str  = f"{sym}usdt"
        key_zset = f"prices:{sym}:ticks"
        cutoff   = now_ts - TICK_WINDOW

        pipe = self.redis.pipeline()
        pipe.set(key_str, price, ex=USDT_TTL)
        pipe.zadd(key_zset, {price: now_ts})
        pipe.zremrangebyscore(key_zset, "-inf", cutoff)
        pipe.expire(key_zset, TICK_TTL)
        pipe.execute()

    # ── USDT: Binance WebSocket ────────────────────────────────────────────────

    async def _binance_stream(self, symbols: set) -> None:
        """
        Binance combined miniTicker stream, ~1 update/second per symbol.
        Message: {"stream":"btcusdt@miniTicker","data":{"s":"BTCUSDT","c":"49853.21"}}
        """
        pairs   = [f"{s}usdt" for s in symbols]
        streams = "/".join(f"{p}@miniTicker" for p in pairs)
        url     = f"{_BINANCE_WS}?streams={streams}"

        log(SERVICE_NAME, "info", "-", f"Binance: connecting ({len(pairs)} pairs)")
        async with websockets.connect(
            url, ping_interval=20, ping_timeout=15, close_timeout=5,
        ) as ws:
            log(SERVICE_NAME, "info", "-", "Binance: connected")
            async for raw in ws:
                msg   = json.loads(raw)
                data  = msg.get("data") if "data" in msg else msg
                sym   = (data.get("s") or "").lower()
                price = data.get("c")
                if sym and price:
                    base = sym[:-4] if sym.endswith("usdt") else sym
                    self._publish_usdt(base, str(price))

    # ── USDT: MEXC WebSocket fallback ──────────────────────────────────────────

    async def _mexc_stream(self, symbols: set) -> None:
        """
        MEXC all-tickers WebSocket stream (single subscription, server pushes all symbols).

        Two important MEXC behaviors:
          1. Uses JSON-level ping {"ping": ts} every ~30s — must reply {"pong": ts}
             to keep connection alive. websockets protocol-level ping is disabled
             (ping_interval=None) because MEXC does not respond to binary pings.
          2. Per-symbol subscription format is spot@public.miniTicker.v3.api@BTCUSDT
             but subscribing to all at once with spot@public.miniTickers.v3.api is
             simpler and avoids sending 300+ subscription messages.
        """
        log(SERVICE_NAME, "info", "-", f"MEXC: connecting (all-tickers stream, tracking {len(symbols)} symbols)")
        async with websockets.connect(
            _MEXC_WS,
            ping_interval=None,   # MEXC manages heartbeat via JSON ping/pong
            close_timeout=5,
        ) as ws:
            await ws.send(json.dumps({
                "method": "SUBSCRIPTION",
                "params": ["spot@public.miniTickers.v3.api"],
            }))
            log(SERVICE_NAME, "info", "-", "MEXC: connected and subscribed")

            async for raw in ws:
                msg = json.loads(raw)

                # Respond to MEXC JSON heartbeat — server closes after ~30s without pong
                if "ping" in msg:
                    await ws.send(json.dumps({"pong": msg["ping"]}))
                    continue

                items = (msg.get("d") or {}).get("items") or []
                for item in items:
                    sym_full = (item.get("s") or "").lower()
                    price    = item.get("c")
                    if not sym_full or not price:
                        continue
                    base = sym_full[:-4] if sym_full.endswith("usdt") else sym_full
                    if base in symbols:
                        self._publish_usdt(base, str(price))

    # ── USDT: Binance REST fallback ────────────────────────────────────────────

    def _fetch_binance_rest_sync(self, symbols: set) -> int:
        """
        Fetch all USDT prices from Binance REST API in one request.
        Runs in a thread since requests is synchronous.
        Returns count of prices stored.
        """
        resp = requests.get(_BINANCE_REST, timeout=10)
        resp.raise_for_status()
        stored = 0
        for item in resp.json():
            sym_full = (item.get("symbol") or "").lower()
            if not sym_full.endswith("usdt"):
                continue
            base = sym_full[:-4]
            if base in symbols:
                price = item.get("price")
                if price:
                    self._publish_usdt(base, str(price))
                    stored += 1
        return stored

    async def _binance_rest_loop(self) -> None:
        """
        Polls Binance REST for USDT prices every REST_POLL seconds.
        Runs in parallel with the WebSocket loop — when WS is active, WS prices
        are fresher and simply overwrite REST prices. When both WS sources are
        down, this prevents Redis keys from expiring (USDT_TTL=90s, REST_POLL=30s).
        """
        log(SERVICE_NAME, "info", "-",
            f"Binance REST: fallback loop starting (every {REST_POLL}s)")
        while self.running:
            try:
                stored = await asyncio.to_thread(
                    self._fetch_binance_rest_sync, self.symbols
                )
                if stored:
                    log(SERVICE_NAME, "info", "-",
                        f"Binance REST: stored {stored} USDT prices")
            except Exception as e:
                log(SERVICE_NAME, "warning", "-",
                    f"Binance REST: poll error ({type(e).__name__}: {e})")
            await asyncio.sleep(REST_POLL)

    # ── USDT: connection manager (Binance → MEXC) ──────────────────────────────

    async def _usdt_stream_with_fallback(self, symbols: set) -> None:
        for name, fn in (("Binance", self._binance_stream), ("MEXC", self._mexc_stream)):
            try:
                await fn(symbols)
                log(SERVICE_NAME, "info", "-", f"{name}: stream closed cleanly")
                return
            except websockets.exceptions.WebSocketException as e:
                log(SERVICE_NAME, "warning", "-",
                    f"{name}: WS error ({type(e).__name__}: {e}) — trying next")
            except Exception as e:
                log(SERVICE_NAME, "warning", "-",
                    f"{name}: error ({type(e).__name__}: {e}) — trying next")
        log(SERVICE_NAME, "error", "-",
            "all USDT WebSocket sources failed — REST fallback loop is still active")

    # ── IRT: Nobitex REST poll ─────────────────────────────────────────────────

    def _fetch_nobitex_sync(self) -> dict:
        """
        Nobitex /market/stats endpoint returns prices in Rials for all active pairs.
        Response: {"status":"ok","stats":{"btc-rls":{"latest":"3400000000"},...}}
        We divide by 10 to convert Rials → Tomans before storing.
        """
        resp = requests.get(
            _NOBITEX_URL,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            raise ValueError(f"Nobitex returned status={data.get('status')}")

        result: dict = {}
        for pair, stats in (data.get("stats") or {}).items():
            parts = pair.split("-")
            if len(parts) != 2 or parts[1] != "rls":
                continue
            sym   = parts[0].lower()
            price = stats.get("latest") or stats.get("dayClose")
            if not price:
                continue
            price_f = float(price)
            if price_f <= 0:
                continue
            result[sym] = str(round(price_f / 10, 2))

        return result

    async def _nobitex_loop(self) -> None:
        """Runs independently — polls Nobitex every NOBITEX_POLL seconds."""
        log(SERVICE_NAME, "info", "-",
            f"Nobitex: starting IRT poll every {NOBITEX_POLL}s")
        while self.running:
            try:
                prices = await asyncio.to_thread(self._fetch_nobitex_sync)
                stored = 0
                for sym, price in prices.items():
                    self.redis.set(f"{sym}irt", price, ex=IRT_TTL)
                    stored += 1
                if stored:
                    log(SERVICE_NAME, "info", "-",
                        f"Nobitex: stored {stored} IRT prices")
            except Exception as e:
                log(SERVICE_NAME, "warning", "-", f"Nobitex: fetch error ({e})")
            await asyncio.sleep(NOBITEX_POLL)

    # ── USDT stream loop (handles reconnect + re-subscribe) ────────────────────

    async def _usdt_loop(self) -> None:
        """Keeps the USDT WebSocket alive, re-subscribes when symbol list changes."""
        while self.running:
            new_symbols = await self._load_symbols()
            if not new_symbols:
                log(SERVICE_NAME, "warning", "-",
                    "no tracked symbols — retrying in 30s")
                await asyncio.sleep(30)
                continue

            if new_symbols != self.symbols:
                self.symbols = new_symbols
                log(SERVICE_NAME, "info", "-",
                    f"tracking {len(self.symbols)} symbols")

            stream_task = asyncio.create_task(
                self._usdt_stream_with_fallback(self.symbols)
            )
            timer_task = asyncio.create_task(asyncio.sleep(RESUB_INTERVAL))

            done, pending = await asyncio.wait(
                {stream_task, timer_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            if stream_task in done:
                exc = stream_task.exception() if not stream_task.cancelled() else None
                if exc:
                    log(SERVICE_NAME, "error", "-",
                        f"USDT stream error: {type(exc).__name__}: {exc} — reconnecting in {RECONNECT_WAIT}s")
                await asyncio.sleep(RECONNECT_WAIT)

    # ── Entry point ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        print(
            f"[{SERVICE_NAME}] Starting\n"
            f"  USDT: Binance WS → MEXC WS (all-tickers) → Binance REST every {REST_POLL}s\n"
            f"  IRT : Nobitex REST every {NOBITEX_POLL}s"
        )
        self.running = True
        self.signal_ready()

        await asyncio.gather(
            self._usdt_loop(),
            self._binance_rest_loop(),
            self._nobitex_loop(),
        )


async def main():
    streamer = PriceStreamer()
    await streamer.run()


if __name__ == "__main__":
    asyncio.run(main())
