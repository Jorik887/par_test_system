import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_cols_cache: Dict[str, Set[str]] = {}
_MAX_LOG_MESSAGE_LEN = 255


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"running", "run", "in_progress"}:
        return "RUNNING"
    if raw in {"success", "passed", "ok"}:
        return "SUCCESS"
    if raw in {"failed", "fail", "error"}:
        return "FAILED"
    return "PENDING"


async def _table_columns(session: AsyncSession, table_name: str) -> Set[str]:
    cached = _cols_cache.get(table_name)
    if cached is not None:
        return cached
    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = :table_name
        """
    )
    result = await session.execute(query, {"table_name": table_name})
    cols = {str(row[0]) for row in result.fetchall()}
    _cols_cache[table_name] = cols
    return cols


async def create_run(session: AsyncSession, name: str) -> int:
    # Dlya sebya: servisnaya operaciya "create run".
    try:
        cols = await _table_columns(session, "test_runs")
        now = datetime.utcnow()
        values: Dict[str, Any] = {"status": _normalize_status("running")}

        if "started_at" in cols:
            values["started_at"] = now
        if "created_at" in cols:
            values["created_at"] = now
        if "name" in cols:
            values["name"] = name

        if not values:
            return 0

        col_list = ", ".join(values.keys())
        bind_list = ", ".join(f":{k}" for k in values.keys())
        stmt = text(f"INSERT INTO test_runs ({col_list}) VALUES ({bind_list}) RETURNING id")
        res = await session.execute(stmt, values)
        run_id = res.scalar_one_or_none()
        return int(run_id or 0)
    except Exception as e:
        logger.warning("Test run logging disabled: cannot create run (%s)", e)
        return 0


async def log_step(
    session: AsyncSession,
    run_id: int,
    step_number: int,
    *,
    request: Optional[str],
    response: Any,
    status: str,
    message: Optional[str] = None,
) -> None:
    # Dlya sebya: servisnaya operaciya "log step".
    if run_id <= 0:
        return
    try:
        cols = await _table_columns(session, "test_run_logs")
        fk_col = "run_id" if "run_id" in cols else ("test_run_id" if "test_run_id" in cols else None)
        if fk_col is None:
            return

        if not isinstance(response, str):
            try:
                response = json.dumps(response, ensure_ascii=False)
            except Exception:
                response = str(response)

        values: Dict[str, Any] = {
            fk_col: run_id,
            "step_number": int(step_number),
            "status": _normalize_status(status),
        }
        if "request" in cols:
            values["request"] = request if isinstance(request, str) else ""
        if "response" in cols:
            values["response"] = response or ""
        if "message" in cols:
            safe_message = str(message or "")
            if len(safe_message) > _MAX_LOG_MESSAGE_LEN:
                safe_message = safe_message[: _MAX_LOG_MESSAGE_LEN - 3] + "..."
            values["message"] = safe_message

        col_list = ", ".join(values.keys())
        bind_list = ", ".join(f":{k}" for k in values.keys())
        stmt = text(f"INSERT INTO test_run_logs ({col_list}) VALUES ({bind_list})")
        await session.execute(stmt, values)
    except Exception as e:
        logger.warning("Test run logging disabled: cannot write step log (%s)", e)


async def finish_run(session: AsyncSession, run_id: int, status: str) -> None:
    # Dlya sebya: servisnaya operaciya "finish run".
    if run_id <= 0:
        return
    try:
        cols = await _table_columns(session, "test_runs")
        updates: Dict[str, Any] = {"id": run_id}
        set_parts = []
        if "finished_at" in cols:
            updates["finished_at"] = datetime.utcnow()
            set_parts.append("finished_at = :finished_at")
        if "status" in cols:
            updates["status"] = _normalize_status(status)
            set_parts.append("status = :status")
        if not set_parts:
            return
        stmt = text(f"UPDATE test_runs SET {', '.join(set_parts)} WHERE id = :id")
        await session.execute(stmt, updates)
    except Exception as e:
        logger.warning("Test run logging disabled: cannot finish run (%s)", e)
