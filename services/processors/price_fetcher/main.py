import asyncio
import requests

from sqlalchemy import text
from core.redis import get_redis
from core.logger import log
from shared.database.session import SessionLocal

FETCH_INTERVAL   = 300
HEALTHCHECK_FILE = "/tmp/worker_ready"
SERVICE_NAME     = "price_fetcher"

KRAKEN_URL = "https://api.kraken.com/0/public/Ticker"
MEXC_URL   = "https://api.mexc.com/api/v3/ticker/price"
BINGX_URL  = "https://open-api.bingx.com/openApi/spot/v1/ticker/24Hr"

_SKIP = {"USDT", "USDC", "BUSD", "DAI"}


class PriceFetcherWorker:
    def __init__(self):
        self.running = False
        self.redis   = get_redis()

    def signal_ready(self):
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
        except Exception as e:
            print(f"[{SERVICE_NAME}] healthcheck write failed: {e}")

    async def _load_tracked_symbols(self) -> list:
        try:
            async with SessionLocal() as session:
                rows = await session.execute(text(
                    "SELECT symbol FROM tracked_coins WHERE is_active = TRUE"
                ))
                return [r[0].upper() for r in rows]
        except Exception as e:
            log(SERVICE_NAME, "error", "-", f"load_tracked_symbols: {e}")
            return []

    # ── Kraken ────────────────────────────────────────────────────────────────

    def _fetch_kraken_sync(self, symbols: list) -> dict:
        # Kraken uses XBT for BTC; build {kraken_pair: base_lower}
        pair_map = {}
        for s in symbols:
            if s in _SKIP:
                continue
            ks = "XBT" if s == "BTC" else s
            pair_map[f"{ks}USDT"] = s.lower()

        resp = requests.get(
            KRAKEN_URL,
            params={"pair": ",".join(pair_map.keys())},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("error", [])
        if errors:
            log(SERVICE_NAME, "warning", "-", f"Kraken partial error: {errors}")
            if not data.get("result"):
                return {}

        result = {}
        for raw_pair, ticker in data.get("result", {}).items():
            price = ticker.get("c", [None])[0]
            if not price or float(price) <= 0:
                continue
            raw_upper = raw_pair.upper()
            for req_pair, base in pair_map.items():
                base_part = req_pair.replace("USDT", "")
                if base_part in raw_upper:
                    result[base] = price
                    break
        return result

    # ── MEXC ──────────────────────────────────────────────────────────────────

    def _fetch_mexc_sync(self, symbols: list) -> dict:
        resp = requests.get(MEXC_URL, timeout=20)
        resp.raise_for_status()
        wanted = {f"{s}USDT" for s in symbols if s not in _SKIP}
        result = {}
        for item in resp.json():
            sym   = item.get("symbol", "")
            price = item.get("price")
            if sym in wanted and price and float(price) > 0:
                result[sym[:-4].lower()] = price
        return result

    # ── BingX ─────────────────────────────────────────────────────────────────

    def _fetch_bingx_sync(self, symbols: list) -> dict:
        resp = requests.get(BINGX_URL, timeout=20)
        resp.raise_for_status()
        raw = resp.json()

        if isinstance(raw, list):
            tickers = raw
        elif isinstance(raw, dict):
            tickers = raw.get("data")
            if not isinstance(tickers, list):
                return {}
        else:
            return {}

        wanted = {f"{s}-USDT" for s in symbols if s not in _SKIP}
        result = {}
        for item in tickers:
            if not isinstance(item, dict):
                continue
            sym   = item.get("symbol", "")
            price = item.get("lastPrice") or item.get("close") or item.get("price")
            if sym in wanted and price and float(price) > 0:
                result[sym.replace("-USDT", "").lower()] = str(price)
        return result

    # ── Fallback chain ────────────────────────────────────────────────────────

    async def _fetch_prices_with_fallback(self, symbols: list) -> dict:
        exchanges = [
            ("Kraken", self._fetch_kraken_sync),
            ("MEXC",   self._fetch_mexc_sync),
            ("BingX",  self._fetch_bingx_sync),
        ]
        for name, fetcher in exchanges:
            try:
                prices = await asyncio.to_thread(fetcher, symbols)
                if prices:
                    log(SERVICE_NAME, "info", "-", f"{name}: got {len(prices)} prices")
                    return prices
                log(SERVICE_NAME, "warning", "-", f"{name}: 0 prices — trying next")
            except Exception as e:
                log(SERVICE_NAME, "warning", "-", f"{name} failed ({e}) — trying next")

        log(SERVICE_NAME, "error", "-", "All exchanges failed this cycle")
        return {}

    def _store_prices(self, prices: dict):
        for base, price in prices.items():
            self.redis.set(f"{base}usdt", price)
        log(SERVICE_NAME, "info", "-", f"Stored {len(prices)} prices in Redis")

    # ── Main cycle ────────────────────────────────────────────────────────────

    async def fetch_and_store(self):
        symbols = await self._load_tracked_symbols()
        if not symbols:
            log(SERVICE_NAME, "warning", "-", "No tracked symbols in DB")
            return
        log(SERVICE_NAME, "info", "-", f"Fetching prices for {len(symbols)} coins")
        prices = await self._fetch_prices_with_fallback(symbols)
        if prices:
            self._store_prices(prices)

    async def run(self):
        print(f"[{SERVICE_NAME}] Starting — every {FETCH_INTERVAL}s "
              f"| fallback: Kraken → MEXC → BingX")
        self.running = True
        self.signal_ready()
        while self.running:
            await self.fetch_and_store()
            await asyncio.sleep(FETCH_INTERVAL)


async def main():
    worker = PriceFetcherWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
