import asyncio
import re
import feedparser
from services.producers.scraper.fetcher import fetch_async


async def fetch_rss_entries(source: dict) -> list:
    raw = await fetch_async(source["rss"])
    feed = await asyncio.to_thread(feedparser.parse, raw)
    filter_cfg = source.get("filter")
    result = []

    for entry in feed.entries:
        if filter_cfg and not _matches(entry, filter_cfg):
            continue
        url = entry.get("link") or entry.get("id")
        if url:
            content_list = entry.get("content", [])
            text = (content_list[0].get("value", "") if content_list else "") or entry.get("summary", "")
            result.append({
                "url": url,
                "title": entry.get("title", ""),
                "text": text,
            })

    return result


def _matches(entry: dict, f: dict) -> bool:
    values = _tag_values(entry, f["tag"])
    return any(re.search(f["value"], v) for v in values)


def _tag_values(entry: dict, tag: str) -> list:
    # feedparser maps <category> to entry.tags as list of dicts with "term" key
    if tag == "category":
        return [t.get("term", "") for t in entry.get("tags", [])]

    val = entry.get(tag)
    if val is None:
        return []
    return [str(val)]
