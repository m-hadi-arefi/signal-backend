
# ─────────────────────────────────────────────────────────────────────────────
# HTTP API SOURCES
#
# فیلدهای هر source:
#
#   url         : آدرس API                                        (اجباری)
#   name        : نام نمایشی                                      (اجباری)
#
#   auth        : احراز هویت                                      (اختیاری)
#       type    : "header" | "query" | "bearer"
#       key     : نام header یا query param  (برای header/query)
#       value   : مقدار کلید یا توکن
#
#   data_path   : dot-notation به items داخل response             (اختیاری)
#                 اگه نبود → خود root  (لیست یا آبجکت)
#
#   id_field    : dot-notation به فیلد unique برای dedup          (اختیاری)
#                 اگه نبود → sha256 کل آیتم
#
#   text_field  : dot-notation به متن داخل آیتم                   (یکی از دو تا)
#   eval        : lambda string روی آیتم، خروجی str               (یکی از دو تا)
#                 اگه هیچکدام نبود → json.dumps(item)
#
# auto-detect لیست/آبجکت:
#   بعد از data_path navigation:
#     list   → برای هر آیتم اجرا می‌شه
#     dict   → یه بار اجرا می‌شه
#     string → همون مستقیم می‌ره
# ─────────────────────────────────────────────────────────────────────────────

SOURCES = [

    # ══════════════════════════════════════════════════════════════════════════
    # BINANCE SQUARE — Signals
    #
    # ساختار response:
    #   {
    #     "code": "000000",
    #     "data": {
    #       "feedData": [
    #         {
    #           "id": "327330...",
    #           "authorName": "PoorCryptoMan",
    #           "content": "$BTC quick look...",
    #           "date": 1779805868,
    #           "webLink": "https://www.binance.com/en/square/post/...",
    #           "tradingPairsV2": [{"symbol": "BTCUSDT", "price": "76889"}],
    #           ...
    #         }
    #       ]
    #     }
    #   }
    #
    # نکته: auth نداره (public API)
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name":      "Binance Square Signals",
        "url":       (
            "https://www.binance.com/bapi/composite/v4/friendly/pgc/content/queryByHashtag"
            "?hashtag=%23signals&pageIndex=1&pageSize=20&orderBy=LATEST"
        ),

        "data_path": "data.feedData",
        "id_field":  "id",

        # هر پست: نام نویسنده + متن کامل سیگنال
        "eval": "lambda item: f\"[{item['authorName']}] {item['content']}\"",
    },

]
