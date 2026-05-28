import re
import asyncio
import json
import os
from rapidfuzz import fuzz


class AnalysisEngine:
    def __init__(self, keywords_path: str, coins_path: str):
        self.keywords_path = keywords_path
        self.coins_path = coins_path

        self.keywords = []
        self.coins = []

    async def load(self):
        print("[DEBUG] load() called")

        await self._load_keywords()
        await self._load_coins()

    # ----------------------
    # LOAD KEYWORDS (FIXED)
    # ----------------------
    async def _load_keywords(self):
        print("[DEBUG] cwd:", os.getcwd())
        print("[DEBUG] file exists:", os.path.exists(self.keywords_path))
        print("[DEBUG] path:", self.keywords_path)

        def _read():
            with open(self.keywords_path, "r", encoding="utf-8") as f:
                data = [x.strip().lower() for x in f if x.strip()]
                print("KEYWORDS LOADED:", len(data))
                return data   # ✅ FIXED

        self.keywords = await asyncio.to_thread(_read)

    # ----------------------
    # LOAD COINS
    # ----------------------
    async def _load_coins(self):
        def _read():
            with open(self.coins_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print("COINS LOADED:", len(data))
                return data

        self.coins = await asyncio.to_thread(_read)

    # ----------------------
    # TEXT CLEANER
    # ----------------------
    def clean_words(self, text: str):
        return re.findall(r'\w+', text.lower())

    # ----------------------
    # ANALYSIS CHECK (FIXED)
    # ----------------------
    async def is_analysis(self, text: str, threshold: int = 85) -> bool:
        text = text.lower()

        def _check():
            best_score = 0

            for kw in self.keywords:

                # 1. exact match (VERY IMPORTANT)
                if kw in text:
                    return True

                # 2. fuzzy match
                score = fuzz.partial_ratio(kw, text)

                if score > best_score:
                    best_score = score

            return best_score >= threshold

        return await asyncio.to_thread(_check)

    # ----------------------
    # COIN EXTRACTOR
    # ----------------------
    async def extract_coin_symbols(self, text: str, threshold: int = 85):
        text_low = text.lower()
        words = self.clean_words(text)
        words_set = set(words)

        result = set()

        def _match_exact(candidate: str) -> bool:
            """Word-level exact match — avoids substring false positives."""
            parts = candidate.split()
            if len(parts) == 1:
                return candidate in words_set
            # multi-word phrase: check as contiguous phrase in text
            return candidate in text_low

        def _search():
            for coin in self.coins:
                name = coin.get("name", "").lower().strip()
                symbol = coin.get("symbol", "").lower().strip()
                faname = coin.get("faName", "").lower().strip()

                if not symbol:
                    continue

                # 1. exact word match
                if _match_exact(symbol) or _match_exact(name) or _match_exact(faname):
                    result.add(symbol)
                    continue

                # 2. fuzzy match — only on name/faName, never on symbol (too short)
                #    both the coin name and the text word must be >= 4 chars
                MIN_LEN = 4
                matched = False
                for w in words:
                    if matched:
                        break
                    if len(w) < MIN_LEN:
                        continue
                    if len(name) >= MIN_LEN and fuzz.ratio(name, w) >= threshold:
                        result.add(symbol)
                        matched = True
                    elif len(faname) >= MIN_LEN and fuzz.ratio(faname, w) >= threshold:
                        result.add(symbol)
                        matched = True

            return list(result)

        return await asyncio.to_thread(_search)