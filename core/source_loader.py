"""
Loads producer source configs from DB.
Returns dicts in the same shape as the static SOURCES lists in sources.py,
so producers need minimal changes.
"""
from typing import List, Dict, Any
from core.db import get_connection


async def load_http_api_sources() -> List[Dict[str, Any]]:
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            "SELECT * FROM http_api_sources WHERE is_active = true ORDER BY id"
        )
        sources = []
        for row in rows:
            s: Dict[str, Any] = {"name": row["name"], "url": row["url"]}
            if row["data_path"]:
                s["data_path"] = row["data_path"]
            if row["id_field"]:
                s["id_field"] = row["id_field"]
            if row["text_field"]:
                s["text_field"] = row["text_field"]
            if row["eval_str"]:
                s["eval"] = row["eval_str"]
            if row["auth_type"]:
                s["auth"] = {
                    "type": row["auth_type"],
                    "key": row["auth_key"],
                    "value": row["auth_value"],
                }
            sources.append(s)
        return sources
    finally:
        await conn.close()


async def load_scraper_sources() -> List[Dict[str, Any]]:
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            "SELECT * FROM scraper_sources WHERE is_active = true ORDER BY id"
        )
        sources = []
        for row in rows:
            s: Dict[str, Any] = {"name": row["name"]}
            if row["rss"]:
                s["rss"] = row["rss"]
            if row["filter_tag"] and row["filter_value"]:
                s["filter"] = {"tag": row["filter_tag"], "value": row["filter_value"]}
            if row["listing_url"]:
                s["listing_url"] = row["listing_url"]
            if row["base_url"]:
                s["base_url"] = row["base_url"]
            if row["box_selector"]:
                s["box_selector"] = row["box_selector"]
            if row["post_selector"]:
                s["post_selector"] = row["post_selector"]
            if row["is_ssr"]:
                s["ssr"] = True
            sources.append(s)
        return sources
    finally:
        await conn.close()
