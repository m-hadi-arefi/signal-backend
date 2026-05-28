
# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER SOURCES
#
# هر source یکی از سه حالت زیر است:
#
#  MODE 1 — RSS
#    فیلد اجباری : rss
#    فیلد اختیاری: filter → {"tag": "<tagXML>", "value": "<regex>"}
#
#  MODE 2 — HTML (صفحه عادی / SSR که requests کافیه)
#    فیلد اجباری : listing_url, base_url
#    فیلد اختیاری: box_selector    → container هر مقاله
#                  post_selector   → لینک مقاله داخل باکس (اگه نبود خودش پیدا می‌کنه)
#                  box_filter      → {"tag": "<CSS>", "value": "<regex>"}
#
#  MODE 3 — SSR (Next.js یا هر فریمورکی که HTML خالی برمی‌گردونه)
#    مثل MODE 2 + فیلد: ssr: True
# ─────────────────────────────────────────────────────────────────────────────

SOURCES = [

    # ══════════════════════════════════════════════════════════════════════════
    # 1. COINTELEGRAPH — Markets
    #
    # وضعیت RSS: فید اصلی (/rss) همه آیتم‌ها رو با category="Latest News"
    #            می‌فرسته — هیچ category اختصاصی برای markets نداره.
    #            فید اختصاصی /markets/rss و /category/markets/rss هر دو 404.
    #
    # راه‌حل: صفحه listing + selector روی href که با /markets/ شروع می‌شه.
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "CoinTelegraph Markets",
        "listing_url": "https://cointelegraph.com/category/markets",
        "base_url": "https://cointelegraph.com",
        "post_selector": 'a[href^="/markets/"]',
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 2. COINDESK — Markets
    #
    # وضعیت RSS: فید اصلی arc/outboundfeeds/rss/ داره.
    #            آیتم‌های markets داخل‌شون category با text="Markets" دارن.
    #            ساختار XML:
    #              <category domain="https://www.coindesk.com/markets">Markets</category>
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "CoinDesk Markets",
        "rss": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "filter": {
            "tag": "category",
            "value": r"^Markets$",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 3. BITCOIN MAGAZINE — Markets
    #
    # وضعیت RSS: فید اصلی /feed داره (WordPress).
    #            آیتم‌های markets داخل‌شون category="MARKETS" دارن.
    #            ساختار XML:
    #              <category><![CDATA[MARKETS]]></category>
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "Bitcoin Magazine Markets",
        "rss": "https://bitcoinmagazine.com/feed",
        "filter": {
            "tag": "category",
            "value": r"^MARKETS$",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 4. U.TODAY — Crypto Market Review
    #
    # وضعیت RSS: فید اختصاصی برای این صفحه پیدا نشد.
    #
    # ساختار HTML (بررسی شده با Chrome inspector):
    #   container : div.news__item
    #   link      : a.news__item-body  (خود کارت لینک هست، href کامله)
    #   تگ‌های کریپتو: div.news__item-tags
    #   نمونه href : https://u.today/zcash-zec-paints-falling-star-...
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "U.Today Market Review",
        "listing_url": "https://u.today/crypto-market-review",
        "base_url": "https://u.today",
        "box_selector": "div.news__item",
        "post_selector": "a.news__item-body",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 5. AMBCRYPTO — Analysis
    #
    # وضعیت RSS: WordPress → فید اختصاصی category داره.
    #            URL: /category/analysis/feed/
    #            همه آیتم‌ها category="Analysis" دارن — فیلتر اضافه لازم نیست.
    #            نکته: سایت روی requests عادی 403 می‌ده ولی RSS کار می‌کنه.
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "AMBCrypto Analysis",
        "rss": "https://ambcrypto.com/category/analysis/feed/",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 6. NOBITEX MAG — تحلیل‌ها
    #
    # وضعیت RSS: WordPress (Jannah theme) → فید اختصاصی category داره.
    #            URL: /mag/category/analysis/feed/
    #            categories در آیتم‌ها:
    #              <category>تحلیل‌ها</category>          ← همیشه هست
    #              <category>تحلیل تکنیکال</category>     ← یا این
    #              <category>تحلیل فاندامنتال</category>  ← یا این
    #              <category>برگزیده</category>           ← اختیاری
    #            فیلتر اضافه لازم نیست — فید از قبل فقط تحلیل می‌ده.
    # ══════════════════════════════════════════════════════════════════════════
    {
        "name": "Nobitex Mag تحلیل‌ها",
        "rss": "https://nobitex.ir/mag/category/analysis/feed/",
    },

]
