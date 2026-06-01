"""
Synchronous psycopg2 database layer for the Flask admin panel.
Completely separate from the async SQLAlchemy/asyncpg used by workers.
"""
import os
import json as _json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import List, Dict, Any, Optional


def _get_dsn():
    return (
        f"host={os.getenv('POSTGRES_HOST', 'postgres')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'events')} "
        f"user={os.getenv('POSTGRES_USER', 'postgres')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'postgres')}"
    )


@contextmanager
def _conn():
    conn = psycopg2.connect(_get_dsn(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Dashboard ─────────────────────────────────────────────────────────────────

def get_dashboard_stats() -> Dict[str, Any]:
    with _conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) AS total FROM pipeline_logs
            WHERE created_at >= CURRENT_DATE
        """)
        total = cur.fetchone()["total"]

        cur.execute("""
            SELECT status, COUNT(*) AS cnt FROM pipeline_logs
            WHERE created_at >= CURRENT_DATE
            GROUP BY status
        """)
        by_status = {row["status"]: row["cnt"] for row in cur.fetchall()}

        cur.execute("""
            SELECT source_name, COUNT(*) AS cnt FROM pipeline_logs
            WHERE created_at >= CURRENT_DATE
              AND source_name IS NOT NULL
              AND step = 'started'
            GROUP BY source_name
            ORDER BY cnt DESC
            LIMIT 10
        """)
        by_source = list(cur.fetchall())

        cur.execute("""
            SELECT trace_id, source_name, service, error_message, created_at
            FROM pipeline_logs
            WHERE status = 'error'
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_errors = list(cur.fetchall())

        cur.execute("""
            SELECT COUNT(DISTINCT trace_id) AS total FROM pipeline_logs
            WHERE created_at >= NOW() - INTERVAL '1 hour'
        """)
        last_hour = cur.fetchone()["total"]

    completed = by_status.get("completed", 0)
    return {
        "total_today": total,
        "last_hour": last_hour,
        "by_status": by_status,
        "by_source": by_source,
        "recent_errors": recent_errors,
        "success_rate": round(completed / total * 100 if total > 0 else 0, 1),
    }


# ── HTTP API Sources ──────────────────────────────────────────────────────────

def get_http_api_sources() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM http_api_sources ORDER BY id")
        return list(cur.fetchall())


def get_http_api_source(source_id: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM http_api_sources WHERE id = %s", (source_id,))
        return cur.fetchone()


def add_http_api_source(data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO http_api_sources
                (name, url, data_path, id_field, text_field, eval_str,
                 auth_type, auth_key, auth_value, is_active, created_at)
            VALUES (%(name)s, %(url)s, %(data_path)s, %(id_field)s, %(text_field)s,
                    %(eval_str)s, %(auth_type)s, %(auth_key)s, %(auth_value)s,
                    %(is_active)s, NOW())
        """, data)


def update_http_api_source(source_id: int, data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE http_api_sources
            SET name=%(name)s, url=%(url)s, data_path=%(data_path)s,
                id_field=%(id_field)s, text_field=%(text_field)s, eval_str=%(eval_str)s,
                auth_type=%(auth_type)s, auth_key=%(auth_key)s, auth_value=%(auth_value)s,
                is_active=%(is_active)s
            WHERE id=%(id)s
        """, {**data, "id": source_id})


def delete_http_api_source(source_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM http_api_sources WHERE id = %s", (source_id,))


# ── Scraper Sources ───────────────────────────────────────────────────────────

def get_scraper_sources() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scraper_sources ORDER BY id")
        return list(cur.fetchall())


def get_scraper_source(source_id: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scraper_sources WHERE id = %s", (source_id,))
        return cur.fetchone()


def add_scraper_source(data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scraper_sources
                (name, rss, filter_tag, filter_value, listing_url, base_url,
                 box_selector, post_selector, is_ssr, is_active, created_at)
            VALUES (%(name)s, %(rss)s, %(filter_tag)s, %(filter_value)s,
                    %(listing_url)s, %(base_url)s, %(box_selector)s, %(post_selector)s,
                    %(is_ssr)s, %(is_active)s, NOW())
        """, data)


def update_scraper_source(source_id: int, data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE scraper_sources
            SET name=%(name)s, rss=%(rss)s, filter_tag=%(filter_tag)s,
                filter_value=%(filter_value)s, listing_url=%(listing_url)s,
                base_url=%(base_url)s, box_selector=%(box_selector)s,
                post_selector=%(post_selector)s, is_ssr=%(is_ssr)s, is_active=%(is_active)s
            WHERE id=%(id)s
        """, {**data, "id": source_id})


def delete_scraper_source(source_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM scraper_sources WHERE id = %s", (source_id,))


# ── Messages ──────────────────────────────────────────────────────────────────

def get_messages(
    page: int = 1,
    per_page: int = 50,
    source: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    conditions = []
    params: Dict = {}

    if source:
        conditions.append("source_name = %(source)s")
        params["source"] = source
    if event_type:
        conditions.append("event_type = %(event_type)s")
        params["event_type"] = event_type
    if status:
        conditions.append("final_status = %(status)s")
        params["status"] = status
    if date_from:
        conditions.append("first_seen >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        conditions.append("first_seen <= %(date_to)s::date + interval '1 day'")
        params["date_to"] = date_to

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page
    params.update({"limit": per_page, "offset": offset})

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            WITH agg AS (
                SELECT
                    trace_id,
                    MIN(created_at) AS first_seen,
                    MAX(created_at) AS last_seen,
                    MIN(source_name) AS source_name,
                    MIN(event_type) AS event_type,
                    array_agg(DISTINCT step ORDER BY step) AS steps,
                    CASE
                        WHEN bool_or(status = 'error') THEN 'error'
                        WHEN bool_or(status = 'completed' AND step = 'final') THEN 'completed'
                        WHEN bool_or(status = 'dropped') THEN 'dropped'
                        ELSE 'in_progress'
                    END AS final_status,
                    MAX(CASE WHEN status = 'dropped' THEN service || ' → ' || step END) AS drop_location
                FROM pipeline_logs
                GROUP BY trace_id
            )
            SELECT * FROM agg {where}
            ORDER BY first_seen DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """, params)
        rows = list(cur.fetchall())

        cur.execute(f"""
            WITH agg AS (
                SELECT trace_id,
                    CASE
                        WHEN bool_or(status = 'error') THEN 'error'
                        WHEN bool_or(status = 'completed' AND step = 'final') THEN 'completed'
                        WHEN bool_or(status = 'dropped') THEN 'dropped'
                        ELSE 'in_progress'
                    END AS final_status,
                    MIN(source_name) AS source_name,
                    MIN(event_type) AS event_type,
                    MIN(created_at) AS first_seen
                FROM pipeline_logs
                GROUP BY trace_id
            )
            SELECT COUNT(*) AS cnt FROM agg {where}
        """, params)
        total = cur.fetchone()["cnt"]

    return {"rows": rows, "total": total, "page": page, "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page)}


def get_message_trace(trace_id: str) -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_type, source_name, service, step, status,
                   ai_signals, error_message, created_at
            FROM pipeline_logs
            WHERE trace_id = %s
            ORDER BY created_at ASC, id ASC
        """, (trace_id,))
        return list(cur.fetchall())


def get_message_sources() -> List[str]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT source_name FROM pipeline_logs
            WHERE source_name IS NOT NULL ORDER BY source_name
        """)
        return [row["source_name"] for row in cur.fetchall()]


# ── Pipeline Funnel ───────────────────────────────────────────────────────────

def get_pipeline_funnel() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                service,
                step,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'started')   AS started,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'completed') AS completed,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'dropped')   AS dropped,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'error')     AS errors,
                COUNT(DISTINCT trace_id) AS total
            FROM pipeline_logs
            WHERE created_at >= CURRENT_DATE
            GROUP BY service, step
            ORDER BY MIN(created_at)
        """)
        return list(cur.fetchall())


def get_worker_activity() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                service,
                COUNT(DISTINCT trace_id)                                      AS total,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'completed') AS completed,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'dropped')   AS dropped,
                COUNT(DISTINCT trace_id) FILTER (WHERE status = 'error')     AS errors,
                MAX(created_at)                                               AS last_activity
            FROM pipeline_logs
            WHERE created_at >= CURRENT_DATE
            GROUP BY service
        """)
        return list(cur.fetchall())


# ── DLQ ───────────────────────────────────────────────────────────────────────

def get_dlq_messages(page: int = 1, per_page: int = 50) -> Dict[str, Any]:
    offset = (page - 1) * per_page
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trace_id, event_type, source_name,
                   service, step, status, error_message, created_at
            FROM pipeline_logs
            WHERE status IN ('error', 'dropped')
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = list(cur.fetchall())

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM pipeline_logs
            WHERE status IN ('error', 'dropped')
        """)
        total = cur.fetchone()["cnt"]

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def get_pipeline_log_by_id(log_id: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pipeline_logs WHERE id = %s", (log_id,))
        return cur.fetchone()


def delete_pipeline_log(log_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM pipeline_logs WHERE id = %s", (log_id,))


# ── Signals viewer ────────────────────────────────────────────────────────────

def _source_link(source: dict) -> Optional[str]:
    """Construct a direct URL to the original source message/article."""
    if not isinstance(source, dict):
        return None
    src_type = source.get("type")
    if src_type == "telegram":
        channel = source.get("channel", "")
        msg_id = source.get("message_id")
        if channel.startswith("@") and msg_id:
            return f"https://t.me/{channel[1:]}/{msg_id}"
    elif src_type == "scraper":
        return source.get("url") or None
    return None


def get_signals(
    page: int = 1,
    per_page: int = 50,
    symbol: Optional[str] = None,
    source_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    conditions: List[str] = []
    params: Dict = {}

    if symbol:
        conditions.append("symbol ILIKE %(symbol)s")
        params["symbol"] = f"%{symbol}%"
    if source_type:
        conditions.append("source->>'type' = %(source_type)s")
        params["source_type"] = source_type
    if date_from:
        conditions.append("created_at >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        conditions.append("created_at <= %(date_to)s::date + interval '1 day'")
        params["date_to"] = date_to

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page
    params.update({"limit": per_page, "offset": offset})

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT s.id, s.symbol, s.trace_id, s.source, s.raw_text,
                   s.ai_summary, s.current_market_price, s.created_at, s.analyzed_at,
                   COUNT(sc.id) AS scenario_count
            FROM signals s
            LEFT JOIN scenarios sc ON sc.signal_id = s.id
            {where}
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """, params)
        rows = list(cur.fetchall())

        cur.execute(f"SELECT COUNT(*) AS cnt FROM signals {where}", params)
        total = cur.fetchone()["cnt"]

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def get_signal_detail(signal_id: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM signals WHERE id = %s", (signal_id,))
        sig = cur.fetchone()
        if not sig:
            return None
        cur.execute("""
            SELECT sc.*, sr.result, sr.pnl_percent, sr.hit_tp, sr.hit_sl, sr.evaluated_at
            FROM scenarios sc
            LEFT JOIN scenario_results sr ON sr.scenario_id = sc.id
            WHERE sc.signal_id = %s
            ORDER BY sc.id
        """, (signal_id,))
        scenarios = list(cur.fetchall())
        return {"signal": sig, "scenarios": scenarios}


def get_signals_api(
    page: int = 1,
    per_page: int = 20,
    symbol: Optional[str] = None,
    source_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """JSON-serialisable version of get_signals — adds computed source.link field."""
    result = get_signals(
        page=page, per_page=per_page,
        symbol=symbol, source_type=source_type,
        date_from=date_from, date_to=date_to,
    )
    rows = []
    for row in result["rows"]:
        source = row["source"] if isinstance(row["source"], dict) else {}
        link = _source_link(source)
        rows.append({
            "id": row["id"],
            "symbol": row["symbol"],
            "trace_id": row["trace_id"],
            "source": {**source, **({"link": link} if link else {})},
            "ai_summary": row["ai_summary"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "analyzed_at": row["analyzed_at"].isoformat() if row["analyzed_at"] else None,
            "scenario_count": row["scenario_count"],
        })
    result["rows"] = rows
    return result


def update_signal(signal_id: int, data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()

        # Build source from structured fields submitted by the admin form
        src_type = data.get("source_type") or ""
        if src_type:
            source_val: dict = {
                "type": src_type,
                "provider": (data.get("source_provider") or "").strip(),
            }
            if src_type == "telegram":
                ch = (data.get("source_channel") or "").strip()
                if ch:
                    source_val["channel"] = ch
                raw_mid = data.get("source_message_id") or ""
                if raw_mid:
                    try:
                        source_val["message_id"] = int(raw_mid)
                    except (ValueError, TypeError):
                        pass
            elif src_type == "scraper":
                url = (data.get("source_url") or "").strip()
                if url:
                    source_val["url"] = url
            elif src_type == "api":
                ext_id = (data.get("source_external_id") or "").strip()
                if ext_id:
                    source_val["external_id"] = ext_id
        else:
            source_val = {}

        price_val = data.get("current_market_price")
        if isinstance(price_val, str):
            try:
                price_val = _json.loads(price_val) if price_val.strip() else None
            except Exception:
                price_val = None

        cur.execute("""
            UPDATE signals
            SET symbol               = %(symbol)s,
                source               = %(source)s,
                ai_summary           = %(ai_summary)s,
                raw_text             = %(raw_text)s,
                current_market_price = %(current_market_price)s,
                analyzed_at          = %(analyzed_at)s
            WHERE id = %(id)s
        """, {
            "id": signal_id,
            "symbol": data.get("symbol"),
            "source": _json.dumps(source_val, ensure_ascii=False),
            "ai_summary": data.get("ai_summary") or None,
            "raw_text": data.get("raw_text") or None,
            "current_market_price": _json.dumps(price_val, ensure_ascii=False) if price_val else None,
            "analyzed_at": data.get("analyzed_at") or None,
        })


def delete_signal(signal_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM signals WHERE id = %s", (signal_id,))


def add_scenario(signal_id: int, data: Dict) -> None:
    import json as _json
    with _conn() as conn:
        cur = conn.cursor()
        tp = data.get("take_profits")
        if isinstance(tp, str):
            try:
                tp = _json.loads(tp) if tp.strip() else []
            except Exception:
                tp = []
        cur.execute("""
            INSERT INTO scenarios
                (signal_id, direction, entry_point, entry_type, take_profits,
                 stop_loss, invalidation, confidence, reasoning, status)
            VALUES
                (%(signal_id)s, %(direction)s, %(entry_point)s, %(entry_type)s,
                 %(take_profits)s, %(stop_loss)s, %(invalidation)s,
                 %(confidence)s, %(reasoning)s, %(status)s)
        """, {
            "signal_id": signal_id,
            "direction": data.get("direction") or None,
            "entry_point": _float_or_none(data.get("entry_point")),
            "entry_type": data.get("entry_type") or None,
            "take_profits": _json.dumps(tp, ensure_ascii=False),
            "stop_loss": _float_or_none(data.get("stop_loss")),
            "invalidation": data.get("invalidation") or None,
            "confidence": _float_or_none(data.get("confidence")),
            "reasoning": data.get("reasoning") or None,
            "status": data.get("status") or "running",
        })


def update_scenario(scenario_id: int, data: Dict) -> None:
    import json as _json
    with _conn() as conn:
        cur = conn.cursor()
        tp = data.get("take_profits")
        if isinstance(tp, str):
            try:
                tp = _json.loads(tp) if tp.strip() else []
            except Exception:
                tp = []
        cur.execute("""
            UPDATE scenarios
            SET direction    = %(direction)s,
                entry_point  = %(entry_point)s,
                entry_type   = %(entry_type)s,
                take_profits = %(take_profits)s,
                stop_loss    = %(stop_loss)s,
                invalidation = %(invalidation)s,
                confidence   = %(confidence)s,
                reasoning    = %(reasoning)s,
                status       = %(status)s
            WHERE id = %(id)s
        """, {
            "id": scenario_id,
            "direction": data.get("direction") or None,
            "entry_point": _float_or_none(data.get("entry_point")),
            "entry_type": data.get("entry_type") or None,
            "take_profits": _json.dumps(tp, ensure_ascii=False),
            "stop_loss": _float_or_none(data.get("stop_loss")),
            "invalidation": data.get("invalidation") or None,
            "confidence": _float_or_none(data.get("confidence")),
            "reasoning": data.get("reasoning") or None,
            "status": data.get("status") or "running",
        })


def delete_scenario(scenario_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM scenarios WHERE id = %s", (scenario_id,))


def _float_or_none(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


# ── Telegram Sources ──────────────────────────────────────────────────────────

def _ensure_telegram_sources_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telegram_sources (
            id         SERIAL PRIMARY KEY,
            name       VARCHAR(255) NOT NULL UNIQUE,
            channel    VARCHAR(255) NOT NULL UNIQUE,
            is_active  BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)


def get_telegram_sources() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_telegram_sources_table(cur)
        cur.execute("SELECT * FROM telegram_sources ORDER BY id")
        return list(cur.fetchall())


def add_telegram_source(data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_telegram_sources_table(cur)
        cur.execute("""
            INSERT INTO telegram_sources (name, channel, is_active, created_at)
            VALUES (%(name)s, %(channel)s, %(is_active)s, NOW())
        """, data)


def update_telegram_source(source_id: int, data: Dict) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_telegram_sources_table(cur)
        cur.execute("""
            UPDATE telegram_sources
            SET name=%(name)s, channel=%(channel)s, is_active=%(is_active)s
            WHERE id=%(id)s
        """, {**data, "id": source_id})


def delete_telegram_source(source_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_telegram_sources_table(cur)
        cur.execute("DELETE FROM telegram_sources WHERE id = %s", (source_id,))


# ── Tracked Coins ─────────────────────────────────────────────────────────────

def _ensure_tracked_coins_table(cur) -> None:
    """Safety net: migration creates the table, but this guards against missing migration."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracked_coins (
            id        SERIAL PRIMARY KEY,
            symbol    VARCHAR(20)  NOT NULL UNIQUE,
            name      VARCHAR(255) NOT NULL DEFAULT '',
            fa_name   VARCHAR(255) NOT NULL DEFAULT '',
            is_active BOOLEAN      NOT NULL DEFAULT TRUE
        )
    """)


def get_tracked_coins(
    page: int = 1,
    per_page: int = 50,
    search: Optional[str] = None,
    active_only: Optional[bool] = None,
) -> Dict[str, Any]:
    conditions: List[str] = []
    params: Dict = {}
    if search:
        conditions.append(
            "(symbol ILIKE %(search)s OR name ILIKE %(search)s OR fa_name ILIKE %(search)s)"
        )
        params["search"] = f"%{search}%"
    if active_only is True:
        conditions.append("is_active = TRUE")
    elif active_only is False:
        conditions.append("is_active = FALSE")

    where  = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page
    params.update({"limit": per_page, "offset": offset})

    with _conn() as conn:
        cur = conn.cursor()
        _ensure_tracked_coins_table(cur)
        cur.execute(
            f"SELECT * FROM tracked_coins {where} ORDER BY symbol LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        rows = list(cur.fetchall())
        cur.execute(f"SELECT COUNT(*) AS cnt FROM tracked_coins {where}", params)
        total = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM tracked_coins WHERE is_active = TRUE")
        active_count = cur.fetchone()["cnt"]

    return {
        "rows": rows,
        "total": total,
        "active_count": active_count,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def set_coin_active(symbol: str, is_active: bool) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_tracked_coins_table(cur)
        cur.execute(
            "UPDATE tracked_coins SET is_active = %s WHERE symbol = %s",
            (is_active, symbol.lower()),
        )


def bulk_set_coins_active(symbols: List[str], is_active: bool) -> None:
    if not symbols:
        return
    symbols = [s.lower() for s in symbols]
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_tracked_coins_table(cur)
        cur.execute(
            "UPDATE tracked_coins SET is_active = %s WHERE symbol = ANY(%s)",
            (is_active, symbols),
        )


def set_all_coins_active(is_active: bool) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_tracked_coins_table(cur)
        cur.execute("UPDATE tracked_coins SET is_active = %s", (is_active,))


def get_active_coin_symbols() -> List[str]:
    with _conn() as conn:
        cur = conn.cursor()
        _ensure_tracked_coins_table(cur)
        cur.execute("SELECT symbol FROM tracked_coins WHERE is_active = TRUE")
        return [row["symbol"] for row in cur.fetchall()]
