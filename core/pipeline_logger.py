"""
Async pipeline logger — writes step-by-step event tracking to pipeline_logs.
Uses asyncpg directly (same as core/db.py).
Swallows all exceptions so logging never kills a worker.
"""
import json
from datetime import datetime
from typing import Optional, Any, Dict

from core.db import get_connection


async def log_pipeline(
    trace_id: str,
    service: str,
    step: str,
    status: str,
    event: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
):
    try:
        event_type = (event or {}).get("type")
        source_name = (event or {}).get("payload", {}).get("source")
        ai_signals = (event or {}).get("signals")
        ai_signals_json = json.dumps(ai_signals) if ai_signals else None

        conn = await get_connection(retries=1, delay=0)
        try:
            await conn.execute(
                """
                INSERT INTO pipeline_logs
                    (trace_id, event_type, source_name, service, step, status,
                     ai_signals, error_message, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
                """,
                trace_id,
                event_type,
                source_name,
                service,
                step,
                status,
                ai_signals_json,
                error_message,
                datetime.utcnow(),
            )
        finally:
            await conn.close()
    except Exception as e:
        print(f"[pipeline_logger] Failed to log {service}/{step}/{status}: {e}")
