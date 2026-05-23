import asyncio
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup

from core.worker import BaseWorker

def clean_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text()

class HTMLCleanerWorker(BaseWorker):
    def __init__(self):
        super().__init__(
            service_name="html_cleaner",
            topic="html-events",
            group_id="html-group"
        )

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw_html = event.get("payload", {}).get("payload", "")
        
        # Extract text from HTML
        event["payload"]["text"] = clean_html(raw_html)
        
        event.setdefault("trace", [])
        if "html" not in event["trace"]:
            event["trace"].append("html")
            
        return event

async def run():
    worker = HTMLCleanerWorker()
    await worker.run()

if __name__ == "__main__":
    asyncio.run(run())
