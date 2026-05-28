import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


# URL path patterns that suggest an article page
ARTICLE_PATTERNS = re.compile(
    r'/(?:news|markets|article|blog|analysis|post|story|mag|20\d{2})/\S+',
    re.IGNORECASE,
)


def extract_post_links(html: str, source: dict) -> list:
    soup = BeautifulSoup(html, "html.parser")
    base_url = source.get("base_url") or source.get("listing_url", "")

    if source.get("box_selector"):
        return _from_boxes(soup, base_url, source)

    if source.get("post_selector"):
        return _with_selector(soup, base_url, source["post_selector"])

    return _auto(soup, base_url)


# ─── box mode ────────────────────────────────────────────────────────────────

def _from_boxes(soup: BeautifulSoup, base_url: str, source: dict) -> list:
    boxes = soup.select(source["box_selector"])
    post_selector = source.get("post_selector")
    box_filter = source.get("box_filter")
    seen = set()
    urls = []

    for box in boxes:
        if box_filter and not _box_matches(box, box_filter):
            continue

        link_el = _find_link(box, post_selector)
        if not link_el:
            continue

        href = link_el.get("href")
        if not href:
            continue

        url = _normalize(href, base_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def _box_matches(box, box_filter: dict) -> bool:
    el = box.select_one(box_filter["tag"])
    if not el:
        return False
    return bool(re.search(box_filter["value"], el.get_text(strip=True)))


def _find_link(box, post_selector: str | None):
    if post_selector:
        return box.select_one(post_selector)
    if box.name == "a":
        return box
    return box.find("a", href=True)


# ─── selector mode (no box) ──────────────────────────────────────────────────

def _with_selector(soup: BeautifulSoup, base_url: str, selector: str) -> list:
    seen = set()
    urls = []

    for el in soup.select(selector):
        href = el.get("href") if el.name == "a" else None
        if not href:
            a = el.find("a", href=True)
            href = a.get("href") if a else None
        if not href:
            continue
        url = _normalize(href, base_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


# ─── auto-detect ─────────────────────────────────────────────────────────────

def _auto(soup: BeautifulSoup, base_url: str) -> list:
    # Try Next.js embedded data first
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if script and script.string:
        try:
            data = json.loads(script.string)
            urls = []
            seen = set()
            _scan_json(data, base_url, urlparse(base_url).netloc, urls, seen)
            if urls:
                return urls
        except Exception:
            pass

    return _heuristic(soup, base_url)


def _scan_json(obj, base_url: str, domain: str, found: list, seen: set):
    if isinstance(obj, str):
        if (obj.startswith("/") or domain in obj) and ARTICLE_PATTERNS.search(obj):
            url = _normalize(obj, base_url)
            if url and url not in seen:
                seen.add(url)
                found.append(url)
    elif isinstance(obj, list):
        for item in obj:
            _scan_json(item, base_url, domain, found, seen)
    elif isinstance(obj, dict):
        for v in obj.values():
            _scan_json(v, base_url, domain, found, seen)


def _heuristic(soup: BeautifulSoup, base_url: str) -> list:
    domain = urlparse(base_url).netloc
    seen = set()
    urls = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != domain:
            continue
        if ARTICLE_PATTERNS.search(parsed.path):
            url = _normalize(href, base_url)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

    return urls


# ─── helpers ─────────────────────────────────────────────────────────────────

def _normalize(href: str, base_url: str) -> str | None:
    try:
        return urljoin(base_url, href).split("?")[0].rstrip("/")
    except Exception:
        return None
