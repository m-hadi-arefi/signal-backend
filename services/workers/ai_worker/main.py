import asyncio
import requests
from typing import Dict, Any, Optional

from core.worker import BaseWorker
from core.redis import get_redis
import os
from services.workers.ai_worker.helper import AnalysisEngine

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

    async def start(self):
        await self.engine.load()
        await super().start()

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:

        text = event.get("payload", {}).get("text", "")
        if not text:
            return None

        print("AI Worker:", text)
        # 1. check analysis
        is_ok = await self.engine.is_analysis(text)
        print("AI Worker ok ?:", is_ok)

        # ❌ NOK → هیچ خروجی نده
        if not is_ok:
            return None  # یا event رو برنگردون

        # 2. extract coins
        coins = await self.engine.extract_coin_symbols(text)
        print("AI Worker coins ?:", coins)

        # ❌ اگر کوینی نبود هم هیچی نده

        if not coins:
            return None

        # 3. append current prices to the prompt
        price_context = self._build_price_context(coins)
        prompt = text + price_context if price_context else text

        # 4. send to AI for full analysis
        ai_result = await asyncio.to_thread(self._call_ai_parser, prompt)
        print("AI Worker ai_result ?:", ai_result)

        if ai_result is None:
            return None

        if isinstance(ai_result, list):
            event["signals"] = ai_result
            event["ai_analysis"] = {"signals": ai_result}
        else:
            event["signals"] = ai_result.get("signals", [])
            event["ai_analysis"] = ai_result

        event.setdefault("trace", [])
        if "ai" not in event["trace"]:
            event["trace"].append("ai")

        return event


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
        url = os.getenv("AI_PARSER_URL", "http://claude-gateway:8000/parse")
        try:
            response = requests.post(
                url,
                json={"prompt": text},
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"AI Parser error: {e}")
            return None


async def run():
    worker = AIWorker()
    await worker.engine.load()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())