from bs4 import BeautifulSoup

_NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside"]


def parse_content(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    return {"title": title, "text": text}
