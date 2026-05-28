"""
Synchronous psycopg2 database layer for the Flask admin panel.
Completely separate from the async SQLAlchemy/asyncpg used by workers.
"""
import os
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

def get_dlq_messages(limit: int = 100) -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT pl.id, pl.trace_id, pl.event_type, pl.source_name,
                   pl.service, pl.step, pl.status, pl.error_message, pl.created_at,
                   e.data AS event_data
            FROM pipeline_logs pl
            LEFT JOIN events e ON pl.trace_id = e.trace_id
            WHERE pl.status IN ('error', 'dropped')
            ORDER BY pl.created_at DESC
            LIMIT %s
        """, (limit,))
        return list(cur.fetchall())


def get_pipeline_log_by_id(log_id: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT pl.*, e.data AS event_data
            FROM pipeline_logs pl
            LEFT JOIN events e ON pl.trace_id = e.trace_id
            WHERE pl.id = %s
        """, (log_id,))
        return cur.fetchone()
