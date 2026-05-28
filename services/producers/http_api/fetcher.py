import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch(source: dict):
    url = source["url"]
    auth = source.get("auth") or {}
    headers = {**HEADERS}
    params = {}

    if auth.get("type") == "header":
        headers[auth["key"]] = auth["value"]
    elif auth.get("type") == "query":
        params[auth["key"]] = auth["value"]
    elif auth.get("type") == "bearer":
        headers["Authorization"] = f"Bearer {auth['value']}"

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()
