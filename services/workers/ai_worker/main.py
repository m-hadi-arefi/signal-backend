import asyncio
import time
import requests
from typing import Dict, Any, Optional, Set

from core.worker import BaseWorker
from core.redis import get_redis
from core.db import get_connection
import os
from services.workers.ai_worker.helper import AnalysisEngine

_TRACKED_COINS_TTL = 300  # reload from DB every 5 minutes


class AIWorker(BaseWorker):
    def __init__(self):
        super().__init__(
            service_name="ai_worker",
            topic="ai-events",
            group_id="ai-group"
        )
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        self.engine = AnalysisEngine(
            keywords_path=os.path.join(BASE_DIR, "mixed.txt"),
            coins_path=os.path.join(BASE_DIR, "coins.json")
        )
        self.redis = get_redis()

        # tracked coins cache
        self._tracked_coins: Set[str] = set()
        self._tracked_coins_loaded_at: float = 0.0

    async def start(self):
        await self.engine.load()
        await super().start()

    # ── Tracked coins from DB ─────────────────────────────────────────────────

    async def _get_tracked_coins(self) -> Set[str]:
        now = time.monotonic()
        if now - self._tracked_coins_loaded_at > _TRACKED_COINS_TTL:
            self._tracked_coins = await self._load_tracked_coins()
            self._tracked_coins_loaded_at = now
            print(f"AI Worker: loaded {len(self._tracked_coins)} active coins from DB")
        return self._tracked_coins

    async def _load_tracked_coins(self) -> Set[str]:
        conn = None
        try:
            conn = await get_connection()
            rows = await conn.fetch(
                "SELECT symbol FROM tracked_coins WHERE is_active = TRUE"
            )
            return {r["symbol"].lower() for r in rows}
        except Exception as e:
            print(f"AI Worker: could not load tracked_coins from DB: {e}")
            # اگر جدول هنوز وجود ندارد، همه سیگنال‌ها رد می‌شوند (fail-open)
            return set()
        finally:
            if conn:
                await conn.close()

    # ── Main processing ───────────────────────────────────────────────────────

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:

        text = event.get("payload", {}).get("text", "")
        if not text:
            return None

        print("AI Worker:", text)

        # 1. check analysis keywords
        is_ok = await self.engine.is_analysis(text)
        print("AI Worker ok?:", is_ok)
        if not is_ok:
            return None

        # 2. extract mentioned coins (from local coins.json — detection)
        coins = await self.engine.extract_coin_symbols(text)
        print("AI Worker coins?:", coins)
        if not coins:
            return None

        # 3. append current prices to prompt
        price_context = self._build_price_context(coins)
        prompt = text + price_context if price_context else text

        # 4. call AI parser
        ai_result = await asyncio.to_thread(self._call_ai_parser, prompt)
        print("AI Worker ai_result?:", ai_result)
        if ai_result is None:
            return None

        # Claude explicitly said the text is not a trading analysis
        if isinstance(ai_result, dict) and ai_result.get("result") == "nok":
            print("AI Worker: Claude rejected text as non-analysis (nok) — dropping")
            return None

        # Gateway always returns a plain list on success; anything else is malformed
        if not isinstance(ai_result, list):
            print(f"AI Worker: unexpected AI parser response type={type(ai_result).__name__} — dropping")
            return None

        raw_signals = ai_result
        if not raw_signals:
            print("AI Worker: AI parser returned empty signal list — dropping")
            return None

        # 5. filter signals by admin-selected tracked coins (from DB)
        filtered_signals = await self._filter_by_tracked_coins(raw_signals)
        if not filtered_signals:
            print(f"AI Worker: all {len(raw_signals)} signal(s) filtered out by tracked_coins")
            return None

        event["signals"] = filtered_signals
        event["ai_analysis"] = {"signals": filtered_signals}

        event.setdefault("trace", [])
        if "ai" not in event["trace"]:
            event["trace"].append("ai")

        return event

    async def _filter_by_tracked_coins(self, signals: list) -> list:
        """Keep only signals whose symbol is in the DB tracked_coins (is_active=TRUE).
        If the table is empty or unreachable → fail-closed (drop all)."""
        active = await self._get_tracked_coins()
        if not active:
            # جدول خالی یا DB در دسترس نیست → چیزی ذخیره نمی‌شود
            print("AI Worker: tracked_coins empty or unreachable — dropping all signals")
            return []
        kept = []
        for sig in signals:
            symbol = (sig.get("symbol") or "").lower().strip()
            if symbol in active:
                kept.append(sig)
            else:
                print(f"AI Worker: filtered signal symbol={symbol!r} (not in tracked_coins)")
        return kept

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_price_context(self, coins: list) -> str:
        lines = []
        for symbol in coins:
            try:
                irt_price = self.redis.get(f"{symbol}irt")
                if irt_price:
                    lines.append(f"now price {symbol.upper()} = {irt_price} IRT")
            except Exception:
                pass
            try:
                usdt_price = self.redis.get(f"{symbol}usdt")
                if usdt_price:
                    lines.append(f"now price {symbol.upper()} = {usdt_price} USDT")
            except Exception:
                pass
        if not lines:
            return ""
        return "\n\n" + "\n".join(lines)

    def _call_ai_parser(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Call the Claude gateway. Returns the parsed JSON on success.
        Raises RuntimeError on network/HTTP errors so BaseWorker routes the
        event to the DLQ instead of silently dropping it.
        """
        url = os.getenv("AI_PARSER_URL", "http://claude-gateway:8000/parse")
        try:
            response = requests.post(
                url,
                json={"prompt": text},
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise RuntimeError(f"AI parser timeout after 60s (url={url})")
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"AI parser unreachable: {e}")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"AI parser HTTP error: {e}")
        except Exception as e:
            raise RuntimeError(f"AI parser unexpected error: {e}")


async def run():
    worker = AIWorker()
    await worker.engine.load()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
