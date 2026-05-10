from bs4 import BeautifulSoup

def parse(html):
    soup = BeautifulSoup(html, "html.parser")

    return {
        "title": soup.title.text,
        "text": soup.get_text(separator=" ", strip=True)
    }