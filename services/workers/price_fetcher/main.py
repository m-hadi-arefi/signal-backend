import asyncio
import requests
import os

from core.redis import get_redis
from core.logger import log

NOBITEX_ORDERBOOK_URL = "https://apiv2.nobitex.ir/v3/orderbook/all"
FETCH_INTERVAL = 300  # 5 minutes
HEALTHCHECK_FILE = "/tmp/worker_ready"

SERVICE_NAME = "price_fetcher"


class PriceFetcherWorker:
    def __init__(self):
        self.running = False
        self.redis = get_redis()

    def signal_ready(self):
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
        except Exception as e:
            print(f"[{SERVICE_NAME}] Failed to create ready signal: {e}")

    def _fetch_orderbook(self) -> dict:
        response = requests.get(
            NOBITEX_ORDERBOOK_URL,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        return response.json()

    def _store_prices(self, data: dict):
        stored = 0
        for key, value in data.items():
            if key == "status":
                continue
            if not isinstance(value, dict):
                continue
            last_trade_price = value.get("lastTradePrice")
            if last_trade_price is None:
                continue
            redis_key = key.lower()
            self.redis.set(redis_key, last_trade_price)
            stored += 1
        log(SERVICE_NAME, "info", "-", f"Stored {stored} prices in Redis")

    async def fetch_and_store(self):
        try:
            data = await asyncio.to_thread(self._fetch_orderbook)
            if data.get("status") != "ok":
                log(SERVICE_NAME, "error", "-", f"API returned non-ok status: {data.get('status')}")
                return
            self._store_prices(data)
        except Exception as e:
            log(SERVICE_NAME, "error", "-", f"Failed to fetch/store prices: {e}")

    async def run(self):
        print(f"[{SERVICE_NAME}] Starting - fetching prices every {FETCH_INTERVAL}s")
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
