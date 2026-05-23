import asyncio
from typing import Dict, Any, Optional

from core.worker import BaseWorker
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

        # 3. build signals
        signals = [
            {
                "signal_type": "general",
                "asset": coin.upper(),
                "notes": text
            }
            for coin in coins
        ]
        print("AI Worker signals ?:", signals)

        event["signals"] = signals

        event.setdefault("trace", [])
        if "ai" not in event["trace"]:
            event["trace"].append("ai")

        return event


async def run():
    worker = AIWorker()
    await worker.engine.load()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())