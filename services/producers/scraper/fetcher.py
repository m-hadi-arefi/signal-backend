import asyncio

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch(url: str, timeout: int = 15) -> str:
    response = requests.get(url, timeout=timeout, headers=HEADERS)
    response.raise_for_status()
    return response.text


async def fetch_async(url: str, timeout: int = 15) -> str:
    return await asyncio.to_thread(fetch, url, timeout)
