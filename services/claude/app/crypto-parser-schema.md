# راهنمای کامل خروجی Crypto Parser

## ساختار کلی — یک آرایه `signals` برای همه ارزها

هر پیامی که به crypto-parser بفرستی، یک JSON با این ساختار برمی‌گرده:

```json
{
  "is_market_related": bool,
  "language": "en|fa|mixed",
  "signals": [
    { /* تحلیل ارز اول */ },
    { /* تحلیل ارز دوم */ },
    { /* ... */ }
  ],
  "raw_summary": string,
  "reasoning": string
}
```

**اگه پیام N تا ارز داشته باشه → N تا آبجکت داخل `signals`**

---

## فیلدهای سطح اول

### `is_market_related`
**نوع:** boolean

```
true  → پیام کریپتو است، signals پر است
false → کریپتو نیست، signals: [] خالی است
```

اولین چیزی که ربات باید چک کنه. اگه `false` بود کل پیام رو رد کن.

---

### `language`
```
"en"    → انگلیسی
"fa"    → فارسی
"mixed" → ترکیبی
```

---

### `signals`
**نوع:** آرایه از `AssetSignal`

**هر آبجکت یک ارز** با تمام اطلاعات تحلیلش.

---

### `raw_summary`
یک جمله خلاصه کل پیام به انگلیسی.
اگه `is_market_related: false` → رشته خالی `""`

---

### `reasoning`
توضیح ۲-۳ جمله‌ای از نحوه parse کردن.

---

## ساختار هر `AssetSignal`

```json
{
  "asset":                  { ... },
  "intents":                [ string ],
  "direction":              "long"|"short"|"neutral"|"conditional"|null,
  "entry":                  { ... } | null,
  "targets":                [ ... ],
  "stop_loss":              { ... } | null,
  "leverage":               number | null,
  "timeframe":              { ... } | null,
  "conditions":             [ string ],
  "sentiment":              string | null,
  "urgency":                string | null,
  "risk_level":             string | null,
  "confidence":             float,
  "ambiguity_score":        float,
  "possible_interpretations": [ string ] | null,
  "technical":              { ... },
  "entities":               { ... }
}
```

---

### `asset`
اطلاعات ارز:
```json
{
  "symbol":     "BTC",      // تیکر بزرگ
  "name":       "Bitcoin",  // نام کامل | null
  "type":       "crypto",   // همیشه "crypto"
  "confidence": 0.99        // اطمینان (0 تا 1)
}
```

**قوانین mapping خاص:**
| ورودی | تبدیل |
|-------|-------|
| `دلار` / `dollar` / `USD` | USDT (Tether) |
| `طلا` / `انس طلا` / `gold` / `XAU` | دو سیگنال جدا: PAXG + XAUT |

---

### `intents`
نوع محتوای این سیگنال (چند تایی):

| مقدار | معنی |
|-------|------|
| `directional_prediction` | پیش‌بینی جهت قیمت |
| `entry_signal` | نقطه ورود مشخص |
| `exit_signal` | نقطه خروج / TP |
| `target_prediction` | تارگت قیمتی |
| `conditional_scenario` | سناریوی شرطی |
| `support_resistance` | سطوح S/R |
| `onchain_alert` | اطلاعات آنچین |
| `whale_activity` | حرکت ولت بزرگ |
| `news_impact` | تاثیر خبر |
| `sentiment_analysis` | احساسات بازار |
| `technical_pattern` | الگوی نموداری |
| `indicator_analysis` | اندیکاتور (RSI, MACD...) |
| `liquidation_funding_oi` | لیکوئیدیشن / فاندینگ / OI |
| `macro_analysis` | تحلیل کلان |
| `volume_orderflow` | حجم / اردربوک |
| `investment_call` | توصیه بلندمدت |
| `risk_warning` | هشدار ریسک |

---

### `direction`
```
"long"        → صعودی / خرید
"short"       → نزولی / فروش
"neutral"     → بی‌جهت / رنج
"conditional" → بستگی به شرط دارد
null          → مشخص نیست
```

---

### `entry`
نقطه ورود:
```json
{
  "price":     65000,   // قیمت ورود | null
  "type":      "limit", // limit | market | breakout | breakdown | null
  "condition": null     // شرط ورود | null
}
```
اگه ورودی نبود → `null`

---

### `targets`
آرایه تارگت‌ها (قیمتی یا زمانی):
```json
[
  {"price": 70000, "label": "tp1",   "timeframe": null},
  {"price": 75000, "label": "tp2",   "timeframe": null},
  {"price": null,  "label": null,    "timeframe": "یه هفته"}
]
```
اگه تارگتی نبود → `[]`

---

### `stop_loss`
```json
{"price": 63000, "condition": null}
```
اگه SL نبود → `null`

---

### `leverage`
عدد اهرم یا `null`:
```
10   → 10x
5    → 5x
null → ذکر نشده
```

---

### `timeframe`
```json
{"value": "4h",       "type": "chart"}
{"value": "یه هفته", "type": "duration"}
{"value": "تا جمعه", "type": "deadline"}
```
اگه نبود → `null`

---

### `conditions`
شرط‌های وابسته:
```json
["اگه 68k رو بگیره و تثبیت کنه", "کندل 4h بالای EMA بسته بشه"]
```
اگه شرطی نبود → `[]`

---

### `sentiment`
```
"very_bullish" | "bullish" | "neutral" | "bearish" | "very_bearish" | "conditional" | null
```

---

### `urgency`
```
"high"   → فوری
"medium" → زمان‌بندی ضمنی
"low"    → بلندمدت
null     → مشخص نیست
```

---

### `risk_level`
```
"high"   → اهرم بالا / بدون SL
"medium" → متعادل
"low"    → محافظه‌کارانه
null     → قابل ارزیابی نیست
```

---

### `confidence`
```
0.90–1.00 → سیگنال کامل و صریح
0.70–0.89 → خوب با ابهام جزئی
0.50–0.69 → نیاز به استنتاج
< 0.50    → ضعیف
```

---

### `ambiguity_score`
```
0.0 → کاملاً واضح
1.0 → کاملاً مبهم
```
اگه بالای **0.4** بود → `possible_interpretations` پر می‌شه.

---

### `technical`
جزئیات تکنیکال این ارز:
```json
{
  "indicators": ["RSI", "MACD"],
  "patterns":   ["symmetrical triangle"],
  "divergences":["bearish hidden divergence"],
  "key_levels": ["67000", "70000"]
}
```

---

### `entities`
موجودیت‌های مرتبط با این ارز:
```json
{
  "exchanges":     ["Binance"],
  "wallets":       [],
  "whale_amounts": ["2500 BTC"],
  "events":        ["halving"],
  "news":          [],
  "people":        ["CZ"],
  "projects":      ["Uniswap"]
}
```

---

## مثال کامل — تحلیل چند ارزی

**ورودی:**
```
BTC long از 65000 تارگت 70000 استاپ 63000 اهرم 10x
ETH short از 3500 تارگت 3100 استاپ 3650
SOL اگه 185 بشکنه تارگت 210 داره
```

**خروجی:**
```json
{
  "is_market_related": true,
  "language": "mixed",
  "signals": [
    {
      "asset": {"symbol": "BTC", "name": "Bitcoin", "type": "crypto", "confidence": 0.99},
      "intents": ["entry_signal", "target_prediction"],
      "direction": "long",
      "entry": {"price": 65000, "type": "limit", "condition": null},
      "targets": [{"price": 70000, "label": "final", "timeframe": null}],
      "stop_loss": {"price": 63000, "condition": null},
      "leverage": 10,
      "timeframe": null,
      "conditions": [],
      "sentiment": "bullish",
      "urgency": null,
      "risk_level": "high",
      "confidence": 0.97,
      "ambiguity_score": 0.03,
      "possible_interpretations": null,
      "technical": {"indicators": [], "patterns": [], "divergences": [], "key_levels": ["65000", "70000", "63000"]},
      "entities": {"exchanges": [], "wallets": [], "whale_amounts": [], "events": [], "news": [], "people": [], "projects": []}
    },
    {
      "asset": {"symbol": "ETH", "name": "Ethereum", "type": "crypto", "confidence": 0.99},
      "intents": ["entry_signal", "target_prediction"],
      "direction": "short",
      "entry": {"price": 3500, "type": "limit", "condition": null},
      "targets": [{"price": 3100, "label": "final", "timeframe": null}],
      "stop_loss": {"price": 3650, "condition": null},
      "leverage": null,
      "timeframe": null,
      "conditions": [],
      "sentiment": "bearish",
      "urgency": null,
      "risk_level": "medium",
      "confidence": 0.96,
      "ambiguity_score": 0.04,
      "possible_interpretations": null,
      "technical": {"indicators": [], "patterns": [], "divergences": [], "key_levels": ["3500", "3100", "3650"]},
      "entities": {"exchanges": [], "wallets": [], "whale_amounts": [], "events": [], "news": [], "people": [], "projects": []}
    },
    {
      "asset": {"symbol": "SOL", "name": "Solana", "type": "crypto", "confidence": 0.98},
      "intents": ["conditional_scenario", "target_prediction"],
      "direction": "conditional",
      "entry": {"price": 185, "type": "breakout", "condition": "if 185 breaks"},
      "targets": [{"price": 210, "label": "final", "timeframe": null}],
      "stop_loss": null,
      "leverage": null,
      "timeframe": null,
      "conditions": ["185 resistance breaks"],
      "sentiment": "conditional",
      "urgency": null,
      "risk_level": "medium",
      "confidence": 0.90,
      "ambiguity_score": 0.10,
      "possible_interpretations": null,
      "technical": {"indicators": [], "patterns": [], "divergences": [], "key_levels": ["185", "210"]},
      "entities": {"exchanges": [], "wallets": [], "whale_amounts": [], "events": [], "news": [], "people": [], "projects": []}
    }
  ],
  "raw_summary": "Three signals: BTC long 65k→70k SL63k 10x, ETH short 3500→3100 SL3650, SOL conditional breakout 185→210.",
  "reasoning": "Three separate assets each with own entry/target/SL. SOL is conditional on breakout."
}
```

---

## چک‌لیست ربات تریدر

```python
data = parse_response(api_response)

if not data["is_market_related"]:
    skip()  # پیام کریپتو نیست

for signal in data["signals"]:
    symbol    = signal["asset"]["symbol"]       # کدوم ارز؟
    direction = signal["direction"]             # long یا short؟
    entry     = signal["entry"]["price"]        # کجا وارد بشیم؟
    sl        = signal["stop_loss"]["price"]    # استاپ کجاست؟
    tp_list   = [t["price"] for t in signal["targets"]]  # تارگت‌ها
    leverage  = signal["leverage"]             # اهرم
    conf      = signal["confidence"]           # اطمینان

    if conf < 0.75:
        skip()  # سیگنال ضعیفه

    if direction == "conditional":
        wait_for_condition(signal["conditions"])

    if signal["ambiguity_score"] > 0.4:
        flag_for_manual_review()

    execute_trade(symbol, direction, entry, sl, tp_list, leverage)
```
