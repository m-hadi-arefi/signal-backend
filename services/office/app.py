import os
import json
import requests as req_lib
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from dotenv import load_dotenv

load_dotenv()

from services.office.auth import auth_bp, login_manager
import services.office.db as db


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "signal-admin-fallback-key-change-in-prod")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "لطفاً ابتدا وارد شوید"
    login_manager.login_message_category = "warning"

    app.register_blueprint(auth_bp)

    # ── Health check (unauthenticated) ────────────────────────────────────────
    @app.route("/ping")
    def ping():
        return "ok"

    # ── Dashboard ─────────────────────────────────────────────────────────────
    @app.route("/")
    @login_required
    def index():
        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        try:
            stats = db.get_dashboard_stats()
        except Exception as e:
            stats = {"error": str(e)}
        services = _ALL_SERVICES
        health = _check_health(services)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return render_template("dashboard.html", stats=stats, health=health, now=now)

    # ── Sources: HTTP API ─────────────────────────────────────────────────────
    @app.route("/sources/http-api")
    @login_required
    def sources_http_api():
        return render_template(
            "sources.html",
            http_sources=db.get_http_api_sources(),
            scraper_sources=db.get_scraper_sources(),
            telegram_sources=db.get_telegram_sources(),
            active_tab="http-api",
        )

    @app.route("/sources/http-api/add", methods=["POST"])
    @login_required
    def sources_http_api_add():
        data = _http_api_form_data()
        try:
            db.add_http_api_source(data)
            flash("سورس جدید اضافه شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_http_api"))

    @app.route("/sources/http-api/<int:sid>/edit", methods=["POST"])
    @login_required
    def sources_http_api_edit(sid):
        data = _http_api_form_data()
        try:
            db.update_http_api_source(sid, data)
            flash("سورس ویرایش شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_http_api"))

    @app.route("/sources/http-api/<int:sid>/delete", methods=["POST"])
    @login_required
    def sources_http_api_delete(sid):
        db.delete_http_api_source(sid)
        flash("سورس حذف شد", "warning")
        return redirect(url_for("sources_http_api"))

    # ── Sources: Scraper ──────────────────────────────────────────────────────
    @app.route("/sources/scraper")
    @login_required
    def sources_scraper():
        return render_template(
            "sources.html",
            http_sources=db.get_http_api_sources(),
            scraper_sources=db.get_scraper_sources(),
            telegram_sources=db.get_telegram_sources(),
            active_tab="scraper",
        )

    @app.route("/sources/scraper/add", methods=["POST"])
    @login_required
    def sources_scraper_add():
        data = _scraper_form_data()
        try:
            db.add_scraper_source(data)
            flash("سورس جدید اضافه شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_scraper"))

    @app.route("/sources/scraper/<int:sid>/edit", methods=["POST"])
    @login_required
    def sources_scraper_edit(sid):
        data = _scraper_form_data()
        try:
            db.update_scraper_source(sid, data)
            flash("سورس ویرایش شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_scraper"))

    @app.route("/sources/scraper/<int:sid>/delete", methods=["POST"])
    @login_required
    def sources_scraper_delete(sid):
        db.delete_scraper_source(sid)
        flash("سورس حذف شد", "warning")
        return redirect(url_for("sources_scraper"))

    # ── Sources: Telegram ─────────────────────────────────────────────────────
    @app.route("/sources/telegram")
    @login_required
    def sources_telegram():
        return render_template(
            "sources.html",
            http_sources=db.get_http_api_sources(),
            scraper_sources=db.get_scraper_sources(),
            telegram_sources=db.get_telegram_sources(),
            active_tab="telegram",
        )

    @app.route("/sources/telegram/add", methods=["POST"])
    @login_required
    def sources_telegram_add():
        data = _telegram_form_data()
        try:
            db.add_telegram_source(data)
            flash("کانال تلگرام اضافه شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_telegram"))

    @app.route("/sources/telegram/<int:sid>/edit", methods=["POST"])
    @login_required
    def sources_telegram_edit(sid):
        data = _telegram_form_data()
        try:
            db.update_telegram_source(sid, data)
            flash("کانال ویرایش شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("sources_telegram"))

    @app.route("/sources/telegram/<int:sid>/delete", methods=["POST"])
    @login_required
    def sources_telegram_delete(sid):
        db.delete_telegram_source(sid)
        flash("کانال حذف شد", "warning")
        return redirect(url_for("sources_telegram"))

    # ── Test Source Endpoints ─────────────────────────────────────────────────
    @app.route("/api/test/http-api", methods=["POST"])
    @login_required
    def test_http_api():
        data = request.get_json(force=True, silent=True) or {}
        result = _test_http_api_source(data)
        return jsonify(result)

    @app.route("/api/test/scraper", methods=["POST"])
    @login_required
    def test_scraper():
        data = request.get_json(force=True, silent=True) or {}
        result = _test_scraper_source(data)
        return jsonify(result)

    # ── Messages ──────────────────────────────────────────────────────────────
    @app.route("/messages")
    @login_required
    def messages():
        page = int(request.args.get("page", 1))
        filters = {
            "source": request.args.get("source") or None,
            "event_type": request.args.get("event_type") or None,
            "status": request.args.get("status") or None,
            "date_from": request.args.get("date_from") or None,
            "date_to": request.args.get("date_to") or None,
        }
        result = db.get_messages(page=page, per_page=50, **filters)
        all_sources = db.get_message_sources()
        return render_template("messages.html", **result, filters=filters, all_sources=all_sources)

    @app.route("/messages/<trace_id>")
    @login_required
    def message_detail(trace_id):
        steps = db.get_message_trace(trace_id)
        return render_template("message_detail.html", trace_id=trace_id, steps=steps)

    # ── DLQ ───────────────────────────────────────────────────────────────────
    @app.route("/dlq")
    @login_required
    def dlq():
        page = int(request.args.get("page", 1))
        result = db.get_dlq_messages(page=page, per_page=50)
        return render_template("dlq.html", **result)

    @app.route("/dlq/replay/<int:log_id>", methods=["POST"])
    @login_required
    def dlq_replay(log_id):
        record = db.get_pipeline_log_by_id(log_id)
        if not record:
            flash("رکورد پیدا نشد", "danger")
            return redirect(url_for("dlq"))
        try:
            from kafka import KafkaProducer
            event = _build_replay_event(record)
            producer = KafkaProducer(
                bootstrap_servers=os.getenv("KAFKA_BROKER", "kafka:9092"),
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            )
            producer.send("engine-events", event)
            producer.flush(timeout=10)
            producer.close()
            flash(f"پیام {record['trace_id'][:8]}... مجدداً ارسال شد", "success")
        except Exception as e:
            flash(f"خطا در replay: {e}", "danger")
        return redirect(url_for("dlq"))

    @app.route("/dlq/<int:log_id>/delete", methods=["POST"])
    @login_required
    def dlq_delete(log_id):
        try:
            db.delete_pipeline_log(log_id)
            flash("رکورد حذف شد", "warning")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("dlq"))

    # ── Signals Viewer ────────────────────────────────────────────────────────
    @app.route("/signals")
    @login_required
    def signals_page():
        page = int(request.args.get("page", 1))
        filters = {
            "symbol": request.args.get("symbol") or None,
            "source_type": request.args.get("source_type") or None,
            "date_from": request.args.get("date_from") or None,
            "date_to": request.args.get("date_to") or None,
        }
        try:
            result = db.get_signals(page=page, per_page=30, **filters)
        except Exception as e:
            result = {"rows": [], "total": 0, "page": 1, "per_page": 30, "total_pages": 1}
            flash(f"خطا در بارگذاری سیگنال‌ها: {e}", "danger")
        return render_template("signals.html", **result, filters=filters)

    @app.route("/signals/<int:signal_id>")
    @login_required
    def signal_detail(signal_id):
        try:
            data = db.get_signal_detail(signal_id)
        except Exception as e:
            flash(f"خطا: {e}", "danger")
            return redirect(url_for("signals_page"))
        if not data:
            flash("سیگنال پیدا نشد", "danger")
            return redirect(url_for("signals_page"))
        return render_template("signal_detail.html", **data)

    @app.route("/signals/<int:signal_id>/edit", methods=["POST"])
    @login_required
    def signal_edit(signal_id):
        try:
            db.update_signal(signal_id, request.form.to_dict())
            flash("سیگنال ویرایش شد", "success")
        except Exception as e:
            flash(f"خطا در ویرایش: {e}", "danger")
        return redirect(url_for("signal_detail", signal_id=signal_id))

    @app.route("/signals/<int:signal_id>/delete", methods=["POST"])
    @login_required
    def signal_delete(signal_id):
        try:
            db.delete_signal(signal_id)
            flash("سیگنال حذف شد", "warning")
        except Exception as e:
            flash(f"خطا در حذف: {e}", "danger")
        return redirect(url_for("signals_page"))

    @app.route("/signals/<int:signal_id>/scenarios/add", methods=["POST"])
    @login_required
    def scenario_add(signal_id):
        try:
            db.add_scenario(signal_id, request.form.to_dict())
            flash("سناریو اضافه شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("signal_detail", signal_id=signal_id))

    @app.route("/signals/<int:signal_id>/scenarios/<int:scenario_id>/edit", methods=["POST"])
    @login_required
    def scenario_edit(signal_id, scenario_id):
        try:
            db.update_scenario(scenario_id, request.form.to_dict())
            flash("سناریو ویرایش شد", "success")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("signal_detail", signal_id=signal_id))

    @app.route("/signals/<int:signal_id>/scenarios/<int:scenario_id>/delete", methods=["POST"])
    @login_required
    def scenario_delete(signal_id, scenario_id):
        try:
            db.delete_scenario(scenario_id)
            flash("سناریو حذف شد", "warning")
        except Exception as e:
            flash(f"خطا: {e}", "danger")
        return redirect(url_for("signal_detail", signal_id=signal_id))

    # ── Tracked Coins ─────────────────────────────────────────────────────────
    @app.route("/coins")
    @login_required
    def coins_page():
        page       = int(request.args.get("page", 1))
        search     = request.args.get("search") or None
        active_filter = request.args.get("active") or None
        active_only = True if active_filter == "1" else (False if active_filter == "0" else None)
        result = db.get_tracked_coins(page=page, per_page=50, search=search, active_only=active_only)
        return render_template("coins.html", **result, search=search or "", active_filter=active_filter or "")

    @app.route("/coins/<symbol>/toggle", methods=["POST"])
    @login_required
    def coin_toggle(symbol):
        is_active = request.form.get("is_active") == "1"
        db.set_coin_active(symbol, is_active)
        return jsonify({"ok": True, "symbol": symbol, "is_active": is_active})

    @app.route("/coins/bulk", methods=["POST"])
    @login_required
    def coins_bulk():
        action  = request.form.get("action")
        symbols = request.form.getlist("symbols")
        if action == "enable":
            db.bulk_set_coins_active(symbols, True)
            flash(f"{len(symbols)} ارز فعال شد", "success")
        elif action == "disable":
            db.bulk_set_coins_active(symbols, False)
            flash(f"{len(symbols)} ارز غیرفعال شد", "warning")
        elif action == "enable_all":
            db.set_all_coins_active(True)
            flash("همه ارزها فعال شدند", "success")
        elif action == "disable_all":
            db.set_all_coins_active(False)
            flash("همه ارزها غیرفعال شدند", "warning")
        return redirect(request.referrer or url_for("coins_page"))

    # ── Health ────────────────────────────────────────────────────────────────
    @app.route("/health")
    @login_required
    def health_page():
        health = _check_health(_ALL_SERVICES)
        try:
            activity = {row["service"]: row for row in db.get_worker_activity()}
        except Exception:
            activity = {}
        return render_template("health.html", health=health, activity=activity)

    # ── Pipeline Funnel ───────────────────────────────────────────────────────
    @app.route("/pipeline")
    @login_required
    def pipeline_page():
        try:
            funnel = db.get_pipeline_funnel()
        except Exception as e:
            funnel = []
            flash(f"خطا در بارگذاری داده‌های pipeline: {e}", "danger")
        return render_template("pipeline.html", funnel=funnel)

    # ── Workers ───────────────────────────────────────────────────────────────
    @app.route("/workers")
    @login_required
    def workers_page():
        health = _check_health(_ALL_SERVICES)
        try:
            activity = {row["service"]: row for row in db.get_worker_activity()}
        except Exception:
            activity = {}
        return render_template("workers.html", health=health, activity=activity, services=_ALL_SERVICES)

    # ── JSON APIs ─────────────────────────────────────────────────────────────
    @app.route("/api/dashboard-stats")
    @login_required
    def api_dashboard_stats():
        try:
            stats = db.get_dashboard_stats()
            health = _check_health(_ALL_SERVICES)
            return jsonify({
                "ok": True,
                "total_today": stats["total_today"],
                "last_hour": stats["last_hour"],
                "by_status": stats["by_status"],
                "success_rate": stats["success_rate"],
                "health": health,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/v1/signals")
    @login_required
    def api_v1_signals():
        page     = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 20)), 100)
        filters  = {
            "symbol":      request.args.get("symbol") or None,
            "source_type": request.args.get("source_type") or None,
            "date_from":   request.args.get("date_from") or None,
            "date_to":     request.args.get("date_to") or None,
        }
        try:
            result = db.get_signals_api(page=page, per_page=per_page, **filters)
            return jsonify({"ok": True, **result})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/health-status")
    @login_required
    def api_health_status():
        try:
            health = _check_health(_ALL_SERVICES)
            activity_rows = db.get_worker_activity()
            activity = {row["service"]: {
                "total": row["total"],
                "completed": row["completed"],
                "dropped": row["dropped"],
                "errors": row["errors"],
                "last_activity": row["last_activity"].strftime("%H:%M:%S") if row["last_activity"] else None,
            } for row in activity_rows}
            return jsonify({"ok": True, "health": health, "activity": activity})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    return app


# ── Constants ─────────────────────────────────────────────────────────────────

_ALL_SERVICES = [
    "engine", "ai-worker",
    "final-store", "http-api-producer", "scraper-producer", "telegram-producer",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_health(services):
    try:
        import redis as redis_lib
        r = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        return {s: r.exists(f"heartbeat:{s}") == 1 for s in services}
    except Exception:
        return {s: False for s in services}


def _http_api_form_data() -> dict:
    f = request.form
    return {
        "name": f.get("name"),
        "url": f.get("url"),
        "data_path": f.get("data_path") or None,
        "id_field": f.get("id_field") or None,
        "text_field": f.get("text_field") or None,
        "eval_str": f.get("eval_str") or None,
        "auth_type": f.get("auth_type") or None,
        "auth_key": f.get("auth_key") or None,
        "auth_value": f.get("auth_value") or None,
        "is_active": "is_active" in f,
    }


def _scraper_form_data() -> dict:
    f = request.form
    return {
        "name": f.get("name"),
        "rss": f.get("rss") or None,
        "filter_tag": f.get("filter_tag") or None,
        "filter_value": f.get("filter_value") or None,
        "listing_url": f.get("listing_url") or None,
        "base_url": f.get("base_url") or None,
        "box_selector": f.get("box_selector") or None,
        "post_selector": f.get("post_selector") or None,
        "is_ssr": "is_ssr" in f,
        "is_active": "is_active" in f,
    }


def _telegram_form_data() -> dict:
    f = request.form
    return {
        "name": f.get("name"),
        "channel": f.get("channel"),
        "is_active": "is_active" in f,
    }


def _test_http_api_source(data: dict) -> dict:
    url = data.get("url", "").strip()
    if not url:
        return {"ok": False, "error": "URL خالی است"}
    try:
        headers = {"User-Agent": "Signal-Admin-Test/1.0", "Accept": "application/json"}
        params = {}
        auth_type = data.get("auth_type") or ""
        if auth_type == "header" and data.get("auth_key"):
            headers[data["auth_key"]] = data.get("auth_value", "")
        elif auth_type == "query" and data.get("auth_key"):
            params[data["auth_key"]] = data.get("auth_value", "")
        elif auth_type == "bearer" and data.get("auth_value"):
            headers["Authorization"] = f"Bearer {data['auth_value']}"

        resp = req_lib.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        status_code = resp.status_code
    except req_lib.exceptions.Timeout:
        return {"ok": False, "error": "timeout — سرور در ۱۵ ثانیه پاسخ نداد"}
    except req_lib.exceptions.ConnectionError as e:
        return {"ok": False, "error": f"خطای اتصال: {e}"}
    except req_lib.exceptions.HTTPError as e:
        return {"ok": False, "error": f"HTTP {resp.status_code}: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        json_data = resp.json()
    except Exception:
        return {"ok": False, "error": f"HTTP {status_code} OK ولی پاسخ JSON نیست (Content-Type: {resp.headers.get('Content-Type','?')})"}

    data_path = (data.get("data_path") or "").strip()
    if data_path:
        for key in data_path.split("."):
            if isinstance(json_data, dict):
                if key not in json_data:
                    return {"ok": False, "error": f"کلید '{key}' در پاسخ پیدا نشد. کلیدهای موجود: {list(json_data.keys())[:10]}"}
                json_data = json_data[key]
            else:
                return {"ok": False, "error": f"مسیر '{data_path}' اشتباه است — در کلید '{key}' به غیر dict رسید"}

    if not isinstance(json_data, list):
        json_data = [json_data] if json_data else []

    item_count = len(json_data)
    sample = ""
    if json_data:
        item = json_data[0]
        eval_str = (data.get("eval_str") or "").strip()
        text_field = (data.get("text_field") or "").strip()
        if eval_str:
            try:
                fn = eval(eval_str)  # noqa: S307 — admin-only endpoint
                sample = str(fn(item))[:400]
            except Exception as e:
                sample = f"⚠️ eval خطا: {e}"
        elif text_field:
            val = item
            for key in text_field.split("."):
                val = val.get(key, "") if isinstance(val, dict) else ""
            sample = str(val)[:400]
        else:
            sample = json.dumps(item, ensure_ascii=False)[:400]

    return {"ok": True, "status_code": status_code, "item_count": item_count, "sample": sample}


def _test_scraper_source(data: dict) -> dict:
    rss = (data.get("rss") or "").strip()
    listing_url = (data.get("listing_url") or "").strip()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Signal-Test/1.0)"}

    if rss:
        try:
            resp = req_lib.get(rss, headers=headers, timeout=15)
            resp.raise_for_status()
        except req_lib.exceptions.Timeout:
            return {"ok": False, "error": "timeout — سرور در ۱۵ ثانیه پاسخ نداد"}
        except req_lib.exceptions.HTTPError as e:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

        try:
            import feedparser
            feed = feedparser.parse(resp.content)
            entries = feed.entries
        except ImportError:
            return {"ok": False, "error": "feedparser نصب نیست"}
        except Exception as e:
            return {"ok": False, "error": f"خطا در پارس RSS: {e}"}

        titles = [e.get("title", "(بدون عنوان)") for e in entries[:5]]
        filtered_count = None
        filter_value = (data.get("filter_value") or "").strip()
        filter_tag = (data.get("filter_tag") or "").strip()
        if filter_tag and filter_value:
            try:
                import re
                pat = re.compile(filter_value, re.IGNORECASE)
                filtered = []
                for e in entries:
                    tags = e.get("tags", []) or []
                    tag_texts = [t.get("term", "") for t in tags if isinstance(t, dict)]
                    direct = str(e.get(filter_tag, ""))
                    combined = " ".join(tag_texts + [direct])
                    if pat.search(combined):
                        filtered.append(e)
                filtered_count = len(filtered)
            except Exception:
                filtered_count = None

        return {"ok": True, "mode": "RSS", "item_count": len(entries),
                "filtered_count": filtered_count, "sample_titles": titles}

    elif listing_url:
        try:
            resp = req_lib.get(listing_url, headers=headers, timeout=15)
            resp.raise_for_status()
        except req_lib.exceptions.Timeout:
            return {"ok": False, "error": "timeout"}
        except req_lib.exceptions.HTTPError as e:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

        post_selector = (data.get("post_selector") or "").strip()
        base_url = (data.get("base_url") or "").strip().rstrip("/")
        if not post_selector:
            return {"ok": True, "mode": "HTML", "item_count": None,
                    "sample_urls": ["✓ صفحه با موفقیت باز شد — post_selector تعریف نشده"]}
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select(post_selector)
            urls = []
            for a in links[:5]:
                href = (a.get("href") or "").strip()
                if href and not href.startswith("http"):
                    href = base_url + href
                if href:
                    urls.append(href)
            return {"ok": True, "mode": "HTML", "item_count": len(links), "sample_urls": urls}
        except ImportError:
            return {"ok": False, "error": "beautifulsoup4 نصب نیست"}
        except Exception as e:
            return {"ok": False, "error": f"خطا در پارس HTML: {e}"}
    else:
        return {"ok": False, "error": "نه RSS URL و نه Listing URL تعریف شده"}


def _build_replay_event(record: dict) -> dict:
    event_type = record.get("event_type") or "unknown"
    pipeline_map = {
        "telegram.message": ["serialize", "ai", "final"],
        "scraped.page":     ["html", "serialize", "ai", "final"],
        "http_api.response": ["serialize", "ai", "final"],
    }
    return {
        "trace_id": record["trace_id"],
        "type": event_type,
        "pipeline": pipeline_map.get(event_type, ["serialize", "ai", "final"]),
        "trace": [],
        "payload": {
            "source": record.get("source_name", ""),
            "text": "",
        },
    }


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG", "0") == "1")
