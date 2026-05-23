import re
def clean_text(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Emoticons
        "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
        "\U0001F680-\U0001F6FF"  # Transport & Map
        "\U0001F1E0-\U0001F1FF"  # Flags
        "\U00002700-\U000027BF"
        "\U000024C2-\U0001F251"
        "\U0001f900-\U0001f9ff"
        "\U00002600-\U000026FF"
        "\U00002B00-\U00002BFF"
        "]+",
        flags=re.UNICODE
    )

    text = emoji_pattern.sub("", text)
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"[@#]\w+", "", text)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text