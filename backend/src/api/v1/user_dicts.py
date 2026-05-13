import asyncio
import base64
import binascii
import logging
import mimetypes
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional
import xml.etree.ElementTree as ET
import uuid
from contextlib import suppress
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import async_session_maker, get_session
from src.config.settings import settings
from src.ishd.client import IshdClient, IshdError
from src.ishd.deps import get_ishd_client
from src.ishd.proto import Ai_Documents_pb2, Ai_Parameters_pb2, Ai_Report_pb2
from src.services import autotest_reports, perf_monitor, test_run_logger, user_dict_xml
from src.services.targets import RuntimeTarget, resolve_runtime_target, resolve_target_id_from_request
from src.paragraph.db import get_paragraph_sessionmaker_by_dsn


_target_ctx: ContextVar[Optional[RuntimeTarget]] = ContextVar("target_ctx", default=None)
_target_client_ctx: ContextVar[Optional[IshdClient]] = ContextVar("target_client_ctx", default=None)
_target_runtime_locks: Dict[str, asyncio.Lock] = {}
_target_cached_clients: Dict[str, IshdClient] = {}
_autotest_run_locks: Dict[str, asyncio.Lock] = {}
_autotest_jobs: Dict[str, Dict[str, Any]] = {}
_autotest_jobs_by_target: Dict[str, str] = {}
_autotest_jobs_lock = asyncio.Lock()
_autotest_job_tasks: Dict[str, asyncio.Task] = {}
_autotest_dicts_cache: Dict[str, Dict[str, Any]] = {}
_autotest_dicts_cache_lock = asyncio.Lock()

logger = logging.getLogger(__name__)

_INSERT_COLUMN_NAME_RE = re.compile(r'Колонка:\s*"([^"]+)"')
_MOJIBAKE_MARK_RE = re.compile(r"[\u0403\u0453\u0409\u040A\u040B\u040C\u040E\u040F\u0459\u045A\u045B\u045C\u045E\u045F]|(?:\u0413\u0452.|\u0413\u2018.)|[\u0413\u0192\u0413\u201A]")
_CYRILLIC_CHAR_RE = re.compile(r"[\u0410-\u042F\u0430-\u044F\u0401\u0451]")
UPLOAD_FILE_VERIFY_TIMEOUT_SEC = 4.0
UPLOAD_FILE_VERIFY_POLL_SEC = 1.0
# Interactive/manual operations should stay responsive in UI.
# Keep enough time for slow stands but avoid long blocking waits by default.
INTERACTIVE_FINAL_ACTION_TIMEOUT_SEC = 6.0
EXECUTE_XML_FINAL_ACTION_TIMEOUT_SEC = 20.0
AUTOTEST_DICTS_LIST_TIMEOUT_SEC = 12.0
AUTOTEST_STEP_FINAL_ACTION_TIMEOUT_SEC = 8.0
AUTOTEST_DICTS_CACHE_TTL_SEC = 60.0
AUTOTEST_ISHD_CONNECT_ATTEMPTS = 3
AUTOTEST_ISHD_CONNECT_RETRY_DELAY_SEC = 1.0


def _repair_mojibake_text(value: str) -> str:
    text = str(value or "")
    if not text or not _MOJIBAKE_MARK_RE.search(text):
        return (
            text.replace("В«", "«")
            .replace("В»", "»")
            .replace("Р’В«", "«")
            .replace("Р’В»", "»")
        )
    try:
        decoded = text.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return text
    src_bad = len(_MOJIBAKE_MARK_RE.findall(text))
    dst_bad = len(_MOJIBAKE_MARK_RE.findall(decoded))
    src_cyr = len(_CYRILLIC_CHAR_RE.findall(text))
    dst_cyr = len(_CYRILLIC_CHAR_RE.findall(decoded))
    repaired = decoded if (dst_bad < src_bad or dst_cyr > src_cyr) else text
    return (
        repaired.replace("В«", "«")
        .replace("В»", "»")
        .replace("Р’В«", "«")
        .replace("Р’В»", "»")
    )

def _target_lock_key(target: RuntimeTarget) -> str:
    # Dlya sebya: serializuem ISHD-zaprosy po konkretnomu stendu, chtoby Paragraph ne rbval sockety.
    target_id = target.id if target.id is not None else "env"
    return (
        f"{target_id}|{target.ishd.host}|{target.ishd.port}|"
        f"{target.ishd.host_id}|{target.ishd.login or ''}"
    )


def _get_target_runtime_lock(target: RuntimeTarget) -> asyncio.Lock:
    # Dlya sebya: odin lock na konkretnyy target v ramkah protsessa backend.
    key = _target_lock_key(target)
    lock = _target_runtime_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _target_runtime_locks[key] = lock
    return lock


def _get_or_create_target_cached_client(target: RuntimeTarget) -> IshdClient:
    # Dlya sebya: derzhim podklyuchennyy ISHD client per target, chtoby ne reconnectit' na kazhdyy klik.
    key = _target_lock_key(target)
    client = _target_cached_clients.get(key)
    if client is not None:
        return client
    client = IshdClient(config=target.ishd)
    _target_cached_clients[key] = client
    return client


def _get_autotest_run_lock(target_id: Optional[int]) -> asyncio.Lock:
    # Dlya sebya: ne daem startovat' 2 odnovremennym autotestam na odin i tot zhe stend.
    key = f"autotest:{target_id if target_id is not None else 'env'}"
    lock = _autotest_run_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _autotest_run_locks[key] = lock
    return lock


def _autotest_target_key(target_id: Optional[int]) -> str:
    return f"target:{target_id if target_id is not None else 'env'}"


def _autotest_job_id() -> str:
    return f"aj_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"


def _autotest_total_steps(payload: "AutoTestRunRequest") -> int:
    # Dlya sebya: bazovye 5 + opcionalnye bloki.
    total = 7  # +2 fail-stepa dlya file smoke (upload/download), mogut byt skipped.
    if payload.include_all_types_smoke:
        total += 2
    if payload.include_create_delete:
        total += 7
    return total


def _clone_job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    # Dlya sebya: chtoby naruzhu ne otdavat sluzhebnye internal-polya.
    public = {
        "job_id": job.get("job_id"),
        "target_id": job.get("target_id"),
        "target_name": job.get("target_name"),
        "source_dict_name": job.get("source_dict_name"),
        "status": job.get("status"),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "finished_at": job.get("finished_at"),
        "progress": job.get("progress", {}),
        "run_id": job.get("run_id"),
        "report_url": job.get("report_url"),
        "error": job.get("error"),
        "cancel_requested": bool(job.get("cancel_requested", False)),
    }
    if "report" in job:
        public["report"] = job["report"]
    return public


async def _autotest_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    async with _autotest_jobs_lock:
        job = _autotest_jobs.get(job_id)
        if job is None:
            return None
        return _clone_job_public(job)


async def _autotest_job_find_running(target_id: Optional[int]) -> Optional[Dict[str, Any]]:
    key = _autotest_target_key(target_id)
    async with _autotest_jobs_lock:
        job_id = _autotest_jobs_by_target.get(key)
        if not job_id:
            return None
        job = _autotest_jobs.get(job_id)
        if not job:
            _autotest_jobs_by_target.pop(key, None)
            return None
        if job.get("status") not in {"queued", "running"}:
            return None
        return _clone_job_public(job)


async def _autotest_job_create(
    *,
    target_id: Optional[int],
    target_name: str,
    payload: "AutoTestRunRequest",
) -> Dict[str, Any]:
    now = _utc_now_iso()
    job_id = _autotest_job_id()
    total_steps = _autotest_total_steps(payload)
    target_key = _autotest_target_key(target_id)
    job: Dict[str, Any] = {
        "job_id": job_id,
        "target_id": target_id,
        "target_name": target_name,
        "target_key": target_key,
        "source_dict_name": payload.source_dict_name,
        "status": "queued",
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
        "run_id": None,
        "report_url": None,
        "error": None,
        "cancel_requested": False,
        "progress": {
            "total_steps": total_steps,
            "completed_steps": 0,
            "percent": 0,
            "current_step": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
        },
    }
    async with _autotest_jobs_lock:
        _autotest_jobs[job_id] = job
        _autotest_jobs_by_target[target_key] = job_id

        # limit in-memory store size
        if len(_autotest_jobs) > 300:
            oldest = sorted(
                _autotest_jobs.values(),
                key=lambda x: str(x.get("updated_at") or ""),
            )[: max(1, len(_autotest_jobs) - 250)]
            for item in oldest:
                if item.get("status") in {"queued", "running"}:
                    continue
                old_job_id = str(item.get("job_id") or "")
                _autotest_jobs.pop(old_job_id, None)
                key = str(item.get("target_key") or "")
                if key and _autotest_jobs_by_target.get(key) == old_job_id:
                    _autotest_jobs_by_target.pop(key, None)

    return _clone_job_public(job)


async def _autotest_job_set_task(job_id: str, task: asyncio.Task) -> None:
    async with _autotest_jobs_lock:
        _autotest_job_tasks[job_id] = task


async def _autotest_job_cancel(job_id: str) -> Optional[Dict[str, Any]]:
    async with _autotest_jobs_lock:
        job = _autotest_jobs.get(job_id)
        if job is None:
            return None
        status = str(job.get("status") or "").strip().lower()
        if status not in {"queued", "running"}:
            return _clone_job_public(job)
        job["cancel_requested"] = True
        job["updated_at"] = _utc_now_iso()
        task = _autotest_job_tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
        return _clone_job_public(job)


async def _autotest_job_update(job_id: str, **changes: Any) -> None:
    async with _autotest_jobs_lock:
        job = _autotest_jobs.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            job[key] = value
        job["updated_at"] = _utc_now_iso()


async def _autotest_job_mark_finished(job_id: str, *, status: str, error: Optional[str] = None) -> None:
    async with _autotest_jobs_lock:
        job = _autotest_jobs.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["error"] = error
        job["finished_at"] = _utc_now_iso()
        job["updated_at"] = job["finished_at"]
        key = str(job.get("target_key") or "")
        if key and _autotest_jobs_by_target.get(key) == job_id:
            _autotest_jobs_by_target.pop(key, None)
        _autotest_job_tasks.pop(job_id, None)


async def _autotest_job_progress(job_id: str, event: Dict[str, Any]) -> None:
    # Dlya sebya: zdes obnovlyaem progress dlya poll UI.
    if not isinstance(event, dict):
        return
    kind = str(event.get("event") or "").strip().lower()
    if not kind:
        return

    async with _autotest_jobs_lock:
        job = _autotest_jobs.get(job_id)
        if job is None:
            return
        if bool(job.get("cancel_requested")) and kind != "finished":
            raise asyncio.CancelledError()
        progress = job.get("progress")
        if not isinstance(progress, dict):
            progress = {}
            job["progress"] = progress

        total = int(progress.get("total_steps") or 0)
        if kind == "started":
            job["status"] = "running"
            total = int(event.get("total_steps") or total or 0)
            progress["total_steps"] = total
            progress["completed_steps"] = int(event.get("completed_steps") or 0)
            progress["percent"] = 0
            progress["current_step"] = None

        elif kind == "step_started":
            index = int(event.get("index") or 0)
            title = str(event.get("title") or "")
            code = str(event.get("code") or "")
            progress["current_step"] = {
                "index": index,
                "title": title,
                "code": code,
                "status": "running",
            }

        elif kind == "step_finished":
            completed = int(event.get("completed_steps") or progress.get("completed_steps") or 0)
            passed = int(event.get("passed") or progress.get("passed") or 0)
            failed = int(event.get("failed") or progress.get("failed") or 0)
            skipped = int(event.get("skipped") or progress.get("skipped") or 0)
            total = int(event.get("total_steps") or total or progress.get("total_steps") or 0)

            progress["completed_steps"] = completed
            progress["passed"] = passed
            progress["failed"] = failed
            progress["skipped"] = skipped
            progress["total_steps"] = total
            progress["current_step"] = {
                "index": int(event.get("index") or completed),
                "title": str(event.get("title") or ""),
                "code": str(event.get("code") or ""),
                "status": str(event.get("status") or ""),
                "message": str(event.get("message") or ""),
                "duration_ms": int(event.get("duration_ms") or 0),
            }
            progress["percent"] = int((completed / total) * 100) if total > 0 else 0

        elif kind == "finished":
            summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
            total = int(summary.get("total") or progress.get("total_steps") or 0)
            progress["total_steps"] = total
            progress["completed_steps"] = total
            progress["passed"] = int(summary.get("passed") or progress.get("passed") or 0)
            progress["failed"] = int(summary.get("failed") or progress.get("failed") or 0)
            progress["skipped"] = int(summary.get("skipped") or progress.get("skipped") or 0)
            progress["percent"] = 100 if total > 0 else 0
            progress["current_step"] = {
                "index": total,
                "title": "Autotest finished",
                "code": "finished",
                "status": str(event.get("status") or ""),
                "message": str(event.get("message") or ""),
            }

        job["updated_at"] = _utc_now_iso()


async def _autotest_connect_with_retry(
    *,
    client: IshdClient,
    runtime_target: RuntimeTarget,
    job_id: str,
) -> None:
    # Dlya sebya: pri kratkih setevyh sboyah ISHD daem neskolko popytok,
    # chtoby fonovyj autotest ne padal srazu na odinochnom Connection lost.
    last_error: Optional[Exception] = None
    for attempt in range(1, AUTOTEST_ISHD_CONNECT_ATTEMPTS + 1):
        try:
            await client.ensure_connected()
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Autotest ISHD connect attempt %s/%s failed (job_id=%s, target=%s): %s",
                attempt,
                AUTOTEST_ISHD_CONNECT_ATTEMPTS,
                job_id,
                runtime_target.name,
                exc,
            )
            with suppress(Exception):
                await client.disconnect()
            if attempt < AUTOTEST_ISHD_CONNECT_ATTEMPTS:
                await asyncio.sleep(AUTOTEST_ISHD_CONNECT_RETRY_DELAY_SEC * attempt)

    raise HTTPException(
        status_code=502,
        detail=(
            f"Cannot connect ISHD target {runtime_target.name} after "
            f"{AUTOTEST_ISHD_CONNECT_ATTEMPTS} attempts: {last_error}"
        ),
    ) from last_error


def _autotest_dicts_cache_key(target_id: Optional[int], source: str) -> str:
    return f"{target_id if target_id is not None else 'env'}|{source}"


async def _autotest_dicts_cache_get(
    target_id: Optional[int],
    source: str,
    *,
    allow_stale: bool = False,
) -> Optional[List[Dict[str, str]]]:
    key = _autotest_dicts_cache_key(target_id, source)
    async with _autotest_dicts_cache_lock:
        item = _autotest_dicts_cache.get(key)
        if not item:
            return None
        ts = float(item.get("ts") or 0.0)
        expired = (datetime.now(timezone.utc).timestamp() - ts) > AUTOTEST_DICTS_CACHE_TTL_SEC
        if expired and not allow_stale:
            _autotest_dicts_cache.pop(key, None)
            return None
        value = item.get("value")
        if not isinstance(value, list):
            return None
        return value


async def _autotest_dicts_cache_set(target_id: Optional[int], source: str, value: List[Dict[str, str]]) -> None:
    key = _autotest_dicts_cache_key(target_id, source)
    async with _autotest_dicts_cache_lock:
        _autotest_dicts_cache[key] = {
            "ts": datetime.now(timezone.utc).timestamp(),
            "value": value,
        }


def _is_target_path_without_ishd_connect(path: str) -> bool:
    # Dlya sebya: nekotorye endpointy ne hodyat v ISHD, im dostatochno target meta.
    normalized = (path or "").rstrip("/")
    if normalized in {
        "/dicts/column-types",
        "/dicts/help",
        "/dicts/autotest/reports",
        "/dicts/autotest/run-async",
        "/dicts/autotest/jobs/current",
    }:
        return True
    if normalized.startswith("/dicts/autotest/reports/"):
        return True
    if normalized.startswith("/dicts/autotest/jobs/"):
        return True
    return False


async def _bind_target_runtime(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: esli peredan target_id, vezhem zapros na profil target i otkryvaem ego ISHD-klient.
    target_id = resolve_target_id_from_request(request)
    if target_id is None:
        token_target = _target_ctx.set(None)
        token_client = _target_client_ctx.set(None)
        try:
            yield
        finally:
            _target_client_ctx.reset(token_client)
            _target_ctx.reset(token_target)
        return

    runtime_target = await resolve_runtime_target(session, target_id)
    if _is_target_path_without_ishd_connect(request.url.path):
        token_target = _target_ctx.set(runtime_target)
        token_client = _target_client_ctx.set(None)
        request.state.runtime_target = runtime_target
        try:
            yield
        finally:
            _target_client_ctx.reset(token_client)
            _target_ctx.reset(token_target)
        return

    target_lock = _get_target_runtime_lock(runtime_target)
    await target_lock.acquire()

    cache_key = _target_lock_key(runtime_target)
    client = _get_or_create_target_cached_client(runtime_target)
    try:
        await client.ensure_connected()
    except Exception as e:
        _target_cached_clients.pop(cache_key, None)
        with suppress(Exception):
            await client.disconnect()
        target_lock.release()
        raise HTTPException(status_code=502, detail=f"Cannot connect ISHD target {runtime_target.name}: {e}")

    token_target = _target_ctx.set(runtime_target)
    token_client = _target_client_ctx.set(client)
    request.state.runtime_target = runtime_target
    try:
        yield
    finally:
        _target_client_ctx.reset(token_client)
        _target_ctx.reset(token_target)
        # РЎРѕРµРґРёРЅРµРЅРёРµ РґРµСЂР¶РёРј РєСЌС€РёСЂРѕРІР°РЅРЅС‹Рј РјРµР¶РґСѓ Р·Р°РїСЂРѕСЃР°РјРё РґР»СЏ СѓСЃРєРѕСЂРµРЅРёСЏ UI/СЂСѓС‡РЅС‹С… РѕРїРµСЂР°С†РёР№.
        # РџСЂРё СЃРµС‚РµРІРѕРј РѕР±СЂС‹РІРµ IshdClient СЃР°Рј СЃР±СЂР°СЃС‹РІР°РµС‚ writer, Рё ensure_connected() СЂРµРєРѕРЅРЅРµРєС‚РёС‚ РЅР° СЃР»РµРґСѓСЋС‰РµРј Р·Р°РїСЂРѕСЃРµ.
        if target_lock.locked():
            target_lock.release()


router = APIRouter(prefix="/dicts", tags=["user-dicts"], dependencies=[Depends(_bind_target_runtime)])


DEFAULT_FILTER_CONDITION = "Р Р°РІРЅРѕ"
DEFAULT_ORDER_DIRECTION = "Р’РѕР·СЂР°СЃС‚Р°РЅРёСЋ"

class DictFilter(BaseModel):
    column: str
    value: str
    condition: str = Field(
        DEFAULT_FILTER_CONDITION,
        description="Filter condition, for example: Equals, Not equals, Contains",
    )


class DictOrder(BaseModel):
    column: str
    direction: str = Field(
        DEFAULT_ORDER_DIRECTION,
        description="Sort direction, for example: Asc, Desc",
    )


class ColumnDef(BaseModel):
    name: str
    type: str = Field(
        "text",
        description=(
            "Column type (key or label). Recommended keys: "
            "uuid, text, text_area, int, double, datetime, date, bool, "
            "link, shape, marker, file, back_link, tle, json, external_link"
        ),
    )
    required: bool = True
    ref_dict: Optional[str] = Field(
        default=None,
        description="For type=link: source dictionary name",
    )
    ref_column: Optional[str] = Field(
        default=None,
        description="For type=link: source dictionary column",
    )
    cascade: bool = Field(
        default=False,
        description="For type=link: cascade delete flag",
    )


class CreateDictRequest(BaseModel):
    name: str
    preset: Optional[str] = Field(
        default=None,
        description="Preset key from /dicts/column-types. Do not use together with columns.",
    )
    columns: Optional[List[ColumnDef]] = None

    @model_validator(mode="after")
    def validate_input(self):
        # Dlya sebya: endpoint "validate_input" ? obrabatyvayu zapros i vozvrashchayu rezultat.
        if self.preset and self.columns:
            raise ValueError("Use either preset or columns, not both")
        return self


class DictNameRequest(BaseModel):
    name: str


class FiltersRequest(BaseModel):
    name: str
    filters: List[DictFilter]


class InsertRowsRequest(BaseModel):
    name: str
    rows: List[Dict[str, Any]] = Field(min_length=1)


class UpdateRowRequest(BaseModel):
    name: str
    row_id: str
    values: Dict[str, Any]


class DownloadFileRequest(BaseModel):
    name: str
    row_id: str
    column: str
    file_index: int = Field(
        default=0,
        ge=0,
        description="Р”Р»СЏ РєРѕР»РѕРЅРѕРє С‚РёРїР° input_file: РёРЅРґРµРєСЃ С„Р°Р№Р»Р° РІ СЃРїРёСЃРєРµ.",
    )


class UploadFileRequest(BaseModel):
    name: str
    row_id: str
    column: str
    filename: str
    data_base64: str = Field(
        description="Base64 payload. Allowed formats: plain base64 or data:*;base64,<payload>.",
    )


class RemoveRowsRequest(BaseModel):
    name: str
    row_ids: Optional[List[str]] = None
    filters: Optional[List[DictFilter]] = None
    allow_many: bool = Field(
        default=False,
        description=(
            "When deleting by filters only: allow deleting multiple matched rows. "
            "By default endpoint blocks bulk delete and asks to pass explicit row_ids."
        ),
    )


class SelectFieldsRequest(BaseModel):
    name: str
    filters: Optional[List[DictFilter]] = None
    order_by: Optional[List[DictOrder]] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    expand_links: bool = False


class RunAllRequest(BaseModel):
    name: str
    keep: bool = True


class AutoTestRunRequest(BaseModel):
    source_dict_name: str = Field(
        description="РќР°Р·РІР°РЅРёРµ РїСЂРµРґСѓСЃС‚Р°РЅРѕРІР»РµРЅРЅРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР° РёР· С‚РµСЃС‚РёСЂСѓРµРјРѕР№ СЃР±РѕСЂРєРё.",
    )
    include_create_delete: bool = Field(
        default=True,
        description="Р”РѕР±Р°РІРёС‚СЊ РїСЂРѕРІРµСЂРєСѓ create/delete РЅР° РІСЂРµРјРµРЅРЅРѕРј СЃРїСЂР°РІРѕС‡РЅРёРєРµ.",
    )
    include_all_types_smoke: bool = Field(
        default=False,
        description=(
            "Р”РѕРї. smoke: СЃРѕР·РґР°С‚СЊ/СѓРґР°Р»РёС‚СЊ РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє СЃ РјР°РєСЃРёРјР°Р»СЊРЅРѕ С€РёСЂРѕРєРёРј "
            "РЅР°Р±РѕСЂРѕРј С‚РёРїРѕРІ РєРѕР»РѕРЅРѕРє."
        ),
    )
    test_prefix: str = Field(
        default="autotest",
        description="РџСЂРµС„РёРєСЃ РґР»СЏ РІСЂРµРјРµРЅРЅС‹С… СЃРїСЂР°РІРѕС‡РЅРёРєРѕРІ.",
    )
    verbose_steps: bool = Field(
        default=False,
        description="Р•СЃР»Рё true вЂ” РІ С€Р°РіР°С… РѕС‚С‡РµС‚Р° СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ request_xml Рё РїРѕР»РЅС‹Р№ payload РѕС‚РІРµС‚Р°.",
    )


def _xml_alias(xml_body: str) -> Optional[str]:
    # Dlya sebya: vspomogatelnyy shag dlya API (xml alias).
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return None
    return root.get("alias")


def _result(resp) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (result).
    ok = resp.report.code == Ai_Report_pb2.ReportCode.DONE
    return {
        "status": "ok" if ok else "fail",
        "report_code": int(resp.report.code),
        "report_code_name": Ai_Report_pb2.ReportCode.Name(resp.report.code),
        "description": resp.report.description,
    }


def _interval_value_to_python(interval: Ai_Parameters_pb2.ValueFromIntervalParameter) -> Any:
    # Dlya sebya: vspomogatelnyy shag dlya API (interval value to python).
    # На некоторых сборках uint может приходить битым (например -4294967295)
    # и protobuf кидает ValueError при доступе к uint_value.
    try:
        if interval.type == Ai_Parameters_pb2.ValueFromIntervalParameter.UINT:
            return interval.value.uint_value
    except (ValueError, TypeError):
        pass
    try:
        if interval.type == Ai_Parameters_pb2.ValueFromIntervalParameter.DOUBLE:
            return interval.value.double_value
    except (ValueError, TypeError):
        pass
    try:
        return interval.value.int_value
    except (ValueError, TypeError):
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    # Dlya sebya: vspomogatelnyy shag dlya API (safe int conversion).
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _datetime_payload_from_element(element: Ai_Parameters_pb2.OneOfParameters) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (datetime payload from proto).
    dt = element.date_time
    raw_time = getattr(dt, "time", None)

    timestamp = _safe_int(getattr(raw_time, "timestamp", 0), 0) if raw_time is not None else 0
    year = _safe_int(getattr(raw_time, "year", 0), 0) if raw_time is not None else 0
    month = _safe_int(getattr(raw_time, "month", 0), 0) if raw_time is not None else 0
    day = _safe_int(getattr(raw_time, "day", 0), 0) if raw_time is not None else 0
    hour = _safe_int(getattr(raw_time, "hour", 0), 0) if raw_time is not None else 0
    minute = _safe_int(getattr(raw_time, "minute", 0), 0) if raw_time is not None else 0
    second = _safe_int(getattr(raw_time, "second", 0), 0) if raw_time is not None else 0

    # In some ISHD payloads only timestamp is present. Build human components
    # from timestamp to avoid parser failures and keep output stable.
    if timestamp and not any([year, month, day]):
        try:
            ts_seconds = timestamp / 1000.0 if timestamp > 10_000_000_000 else float(timestamp)
            parsed_dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
            year = parsed_dt.year
            month = parsed_dt.month
            day = parsed_dt.day
            hour = parsed_dt.hour
            minute = parsed_dt.minute
            second = parsed_dt.second
        except (OverflowError, OSError, ValueError):
            pass

    payload: Dict[str, Any] = {
        "type": int(dt.type),
        "time": {
            "timestamp": timestamp,
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "minute": minute,
            "second": second,
        },
        "range": bool(getattr(dt, "range", False)),
    }
    mask = str(getattr(dt, "mask", "") or "").strip()
    if mask:
        payload["mask"] = mask
    return payload


def _oneof_to_python(element: Ai_Parameters_pb2.OneOfParameters) -> Any:
    # Dlya sebya: vspomogatelnyy shag dlya API (oneof to python).
    param_type = element.type
    if param_type == Ai_Parameters_pb2.OneOfParameters.TEXT_FIELD:
        return element.text_field.text
    if param_type == Ai_Parameters_pb2.OneOfParameters.CHECK_BOX:
        return bool(element.check_box.checked)
    if param_type == Ai_Parameters_pb2.OneOfParameters.COMBO_BOX:
        values = list(element.combo_box.values)
        selected: List[str] = []
        for idx in element.combo_box.current_index:
            if 0 <= idx < len(values):
                selected.append(values[idx])
        return selected[0] if len(selected) == 1 else selected
    if param_type == Ai_Parameters_pb2.OneOfParameters.INTERVAL:
        return _interval_value_to_python(element.interval)
    if param_type == Ai_Parameters_pb2.OneOfParameters.DATE_TIME:
        return _datetime_payload_from_element(element)
    if param_type == Ai_Parameters_pb2.OneOfParameters.LINK:
        return {
            "link": element.link.link,
            "title": element.link.title,
        }
    if param_type == Ai_Parameters_pb2.OneOfParameters.INPUT_FILE:
        files: List[Dict[str, Any]] = []
        for info in element.files.file_info:
            payload: Dict[str, Any] = {
                "id": str(getattr(info, "id", "")),
                "name": str(getattr(info, "name", "")),
                "size": int(getattr(info, "size", 0) or 0),
                "path": str(getattr(info, "path", "")),
                "session_id": str(getattr(info, "session_id", "")),
            }
            data = bytes(getattr(info, "data", b"") or b"")
            if data:
                payload["data_base64"] = base64.b64encode(data).decode("ascii")
            files.append(payload)
        return files
    if param_type == Ai_Parameters_pb2.OneOfParameters.BINARY_DATA_PARAM:
        data = bytes(element.binary_param.data or b"")
        payload: Dict[str, Any] = {
            "filename": str(element.binary_param.filename or ""),
            "description": str(element.binary_param.description or ""),
            "size_bytes": len(data),
        }
        if data:
            payload["data_base64"] = base64.b64encode(data).decode("ascii")
        return payload
    if param_type == Ai_Parameters_pb2.OneOfParameters.GROUP:
        data: Dict[str, Any] = {}
        for child in element.group.parameters:
            key = child.alias or child.name or f"param_{child.id}"
            value = _oneof_to_python(child.element)
            if key in data:
                if isinstance(data[key], list):
                    data[key].append(value)
                else:
                    data[key] = [data[key], value]
            else:
                data[key] = value
        return data
    if param_type == Ai_Parameters_pb2.OneOfParameters.REPEATER:
        rows: List[Dict[str, Any]] = []
        for item in element.repeater.data:
            row: Dict[str, Any] = {}
            if item.name:
                row["_name"] = item.name
            for child in item.view:
                key = child.alias or child.name or f"param_{child.id}"
                value = _oneof_to_python(child.element)
                if key in row:
                    if isinstance(row[key], list):
                        row[key].append(value)
                    else:
                        row[key] = [row[key], value]
                else:
                    row[key] = value
            rows.append(row)
        return rows
    if param_type == Ai_Parameters_pb2.OneOfParameters.TABLE:
        columns: List[Dict[str, str]] = []
        for idx, title in enumerate(element.table.title):
            key = title.alias or title.name or f"col_{idx}"
            columns.append({"key": key, "name": title.name, "alias": title.alias})
        rows: List[Any] = []
        for row in element.table.rows:
            values = [_oneof_to_python(cell) for cell in row.elements]
            if columns and len(columns) == len(values):
                rows.append({col["key"]: value for col, value in zip(columns, values)})
            else:
                rows.append(values)
        return {"columns": columns, "rows": rows}
    return None


def _action_request_to_python(
    action_request: Optional[Ai_Documents_pb2.SendActionRequest],
) -> Optional[Dict[str, Any]]:
    # Dlya sebya: vspomogatelnyy shag dlya API (action request to python).
    if action_request is None:
        return None
    action = action_request.action
    return {
        "state": action.state,
        "button": action.button,
        "description": action.description,
        "items": [
            {
                "id": p.id,
                "alias": p.alias,
                "name": p.name,
                "value": _oneof_to_python(p.element),
            }
            for p in action.items
        ],
    }


def _collect_tables(value: Any) -> List[Dict[str, Any]]:
    # Dlya sebya: vspomogatelnyy shag dlya API (collect tables).
    tables: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        # Dlya sebya: endpoint "walk" ? obrabatyvayu zapros i vozvrashchayu rezultat.
        if isinstance(node, dict):
            if "columns" in node and "rows" in node and isinstance(node["rows"], list):
                tables.append(node)
            for child in node.values():
                walk(child)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return tables


def _extract_row_ids_from_tables(tables: List[Dict[str, Any]]) -> List[str]:
    # Dlya sebya: vspomogatelnyy shag dlya API (extract row ids from tables).
    row_ids: List[str] = []
    seen: set[str] = set()
    for table in tables:
        rows = table.get("rows", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_row_id = row.get("uuid")
            if raw_row_id is None:
                continue
            row_id = str(raw_row_id).strip()
            if not row_id or row_id in seen:
                continue
            seen.add(row_id)
            row_ids.append(row_id)
    return row_ids


_UUID_TOKEN_RE = re.compile(
    r"[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}"
)


def _extract_uuid_tokens_from_text(raw: Any) -> List[str]:
    # Dlya sebya: vydelяем UUID даzhe iz stroki-vkladki vida `data: "{uuid}"`.
    text_value = str(raw or "").strip()
    if not text_value:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for token in _UUID_TOKEN_RE.findall(text_value):
        try:
            normalized = str(uuid.UUID(token))
        except ValueError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _extract_file_id_candidates_from_value(value: Any) -> List[str]:
    # Dlya sebya: sobiraem file_id kandidatov iz payload kolонки faila dlya documentfilesget.
    out: List[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        raw_text = str(raw or "").strip()
        if raw_text:
            key = f"raw::{raw_text}"
            if key not in seen:
                seen.add(key)
                out.append(raw_text)
        for token in _extract_uuid_tokens_from_text(raw):
            brace = "{" + token + "}"
            if brace in seen:
                continue
            seen.add(brace)
            out.append(brace)

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, (str, uuid.UUID)):
            _add(node)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            for key in ("file_id", "id", "uuid", "value", "values", "file", "files", "items"):
                if key in node:
                    _walk(node.get(key))
            for item in node.values():
                _walk(item)

    _walk(value)
    return out


def _extract_file_blob_from_value(value: Any, *, file_index: int = 0) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (extract file blob from value).
    candidates: List[Dict[str, Any]] = []
    direct_path: Optional[str] = None

    def _configured_file_dirs() -> List[str]:
        raw = str(getattr(settings, "paragraph_file_dirs", "") or "").strip()
        parts: List[str] = []
        if raw:
            for item in raw.replace(";", ",").split(","):
                v = str(item or "").strip().strip('"')
                if v:
                    parts.append(v)
        if not parts:
            parts = [r"C:\documents_files"]
        out: List[str] = []
        seen: set[str] = set()
        for d in parts:
            norm = os.path.normpath(d)
            key = norm.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(norm)
        return out

    def _extract_windows_path_hint(text: str) -> Optional[str]:
        value = str(text or "").strip()
        if not value:
            return None
        # Handle payloads like "127.0.0.1 C:\\documents_files\\file.png"
        m = re.search(r"[A-Za-z]:\\[^\r\n]*", value)
        if m:
            return m.group(0).strip().strip('"')
        return None

    def _read_if_exists(path_like: Optional[str], *, filename_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        p = str(path_like or "").strip().strip('"')
        if not p:
            return None
        if os.path.isfile(p):
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
            except OSError:
                # Файл может быть временно недоступен по правам/блокировке; продолжаем fallback-цепочку.
                return None
            name = str(filename_hint or "").strip() or os.path.basename(p)
            return {"filename": name or None, "bytes": data}
        return None

    def _read_by_filename_lookup(name_like: Optional[str]) -> Optional[Dict[str, Any]]:
        name = os.path.basename(str(name_like or "").strip().strip('"'))
        if not name:
            return None
        for base_dir in _configured_file_dirs():
            candidate = os.path.join(base_dir, name)
            hit = _read_if_exists(candidate, filename_hint=name)
            if hit:
                return hit
        return None

    if isinstance(value, dict):
        candidates.append(value)
    elif isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
    elif isinstance(value, str):
        direct_path = value.strip()
        from_path = _read_if_exists(direct_path)
        if from_path:
            return from_path
        from_path_hint = _read_if_exists(_extract_windows_path_hint(direct_path))
        if from_path_hint:
            return from_path_hint
        from_name_lookup = _read_by_filename_lookup(direct_path)
        if from_name_lookup:
            return from_name_lookup
        # Some builds may return plain base64 string for file payload.
        try:
            data = base64.b64decode(direct_path, validate=True)
            if data:
                return {"filename": None, "bytes": data}
        except (ValueError, binascii.Error):
            pass

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail="Value in selected column is not a downloadable file payload.",
        )

    if file_index >= len(candidates):
        raise HTTPException(
            status_code=400,
            detail=f"file_index out of range: {file_index}, available: {len(candidates)}",
        )

    payload = candidates[file_index]
    raw_b64 = payload.get("data_base64") or payload.get("content_base64") or payload.get("base64")
    if raw_b64 is None:
        raw_b64 = payload.get("data")

    if raw_b64 is None and isinstance(payload.get("value"), (dict, list, str)):
        try:
            nested_blob = _extract_file_blob_from_value(payload.get("value"), file_index=0)
            nested_name = str(payload.get("filename") or payload.get("name") or "").strip() or nested_blob.get("filename")
            return {"filename": nested_name or None, "bytes": bytes(nested_blob.get("bytes") or b"")}
        except HTTPException:
            pass

    if isinstance(raw_b64, (bytes, bytearray)):
        data = bytes(raw_b64)
        filename = str(payload.get("filename") or payload.get("name") or "").strip() or None
        return {"filename": filename, "bytes": data}
    if isinstance(raw_b64, list) and raw_b64 and all(isinstance(v, int) and 0 <= v <= 255 for v in raw_b64):
        data = bytes(raw_b64)
        filename = str(payload.get("filename") or payload.get("name") or "").strip() or None
        return {"filename": filename, "bytes": data}

    if not raw_b64:
        path_hint = str(payload.get("path") or payload.get("file_path") or "").strip()
        filename_hint = str(payload.get("filename") or payload.get("name") or "").strip() or None
        from_path = _read_if_exists(path_hint, filename_hint=filename_hint)
        if from_path:
            return from_path
        from_path_hint = _read_if_exists(_extract_windows_path_hint(path_hint), filename_hint=filename_hint)
        if from_path_hint:
            return from_path_hint
        from_name_lookup = _read_by_filename_lookup(filename_hint or path_hint)
        if from_name_lookup:
            return from_name_lookup
        raise HTTPException(
            status_code=400,
            detail="File payload does not contain base64 data or readable file path.",
        )

    raw_b64_str = str(raw_b64).strip()
    if raw_b64_str.startswith("base64,"):
        raw_b64_str = raw_b64_str[7:].strip()
    if raw_b64_str.startswith("data:") and ";base64," in raw_b64_str:
        raw_b64_str = raw_b64_str.split(";base64,", 1)[1].strip()

    try:
        data = base64.b64decode(raw_b64_str, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="File payload contains invalid base64 data.") from exc

    filename = str(payload.get("filename") or payload.get("name") or "").strip() or None
    return {"filename": filename, "bytes": data}


def _has_downloadable_file_payload(value: Any) -> bool:
    # Dlya sebya: vspomogatelnyy shag dlya API (has downloadable file payload).
    try:
        blob = _extract_file_blob_from_value(value, file_index=0)
        return bool(blob.get("bytes"))
    except HTTPException:
        return False


def _decode_base64_payload(raw: str) -> bytes:
    # Dlya sebya: universal'nyy parser base64 iz UI (plain ili data-url).
    value = str(raw or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="data_base64 must not be empty.")
    if value.startswith("base64,"):
        value = value[7:].strip()
    if value.startswith("data:") and ";base64," in value:
        value = value.split(";base64,", 1)[1].strip()
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="data_base64 contains invalid base64 payload.") from exc


def _guess_media_type_from_filename(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(str(filename or ""))
    return guessed or "application/octet-stream"


def _error_source_label_ru(source: str) -> str:
    if source == "paragraph_api":
        return "интегратора Параграфа"
    return "системы тестирования"


def _detect_error_source(status: str, message: str) -> str:
    step_status = str(status or "").strip().lower()
    if step_status not in {"failed", "skipped"}:
        return ""
    text = str(message or "").strip().lower()
    if not text:
        return "test_system"
    paragraph_markers = (
        "paragraph",
        "ishd",
        "invalid vector subscript",
        "connect ishd",
        "connection lost",
        "final action timeout",
        "rest get",
        "path '/api",
        "ошибка ishd",
        "транспортная ошибка",
        "accepted, file not materialized",
        "likely paragraph/integrator-side issue",
    )
    if any(marker in text for marker in paragraph_markers):
        return "paragraph_api"
    return "test_system"


def _attach_error_source_prefix(message: str, source: str, status: str) -> str:
    if str(status or "").strip().lower() not in {"failed", "skipped"}:
        return message
    base = str(message or "").strip()
    if not source:
        return base
    if "Источник:" in base:
        return base
    return f"Источник: {_error_source_label_ru(source)}. {base}" if base else f"Источник: {_error_source_label_ru(source)}."


def _extract_file_columns_from_frames(frames: List[Dict[str, Any]]) -> List[str]:
    # Dlya sebya: nahodim kolonki s failami iz query_frame.
    # РџРѕРґРґРµСЂР¶РёРІР°РµРј РєР°Рє API-РєР»СЋС‡Рё (file/input_file), С‚Р°Рє Рё СЂСѓСЃСЃРєРёРµ РїРѕРґРїРёСЃРё С‚РёРїР°.
    out: List[str] = []
    seen: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        columns = frame.get("columns")
        if not isinstance(columns, list):
            continue
        for col in columns:
            if not isinstance(col, dict):
                continue
            name = str(col.get("name") or "").strip()
            raw_col_type = col.get("type")
            col_type = str(raw_col_type or "").strip().lower()
            if not name:
                continue
            normalized = col_type.replace("-", "_")
            numeric_type: Optional[int] = None
            try:
                numeric_type = int(raw_col_type) if raw_col_type is not None else None
            except (TypeError, ValueError):
                numeric_type = None
            if (
                "file" not in normalized
                and "С„Р°Р№Р»" not in normalized
                and "РІР»РѕР¶" not in normalized
                and "РґРѕРєСѓРјРµРЅС‚" not in normalized
                and numeric_type not in {9, 11}
            ):
                continue
            marker = name.lower()
            if marker in seen:
                continue
            seen.add(marker)
            out.append(name)
    return out


def _extract_file_columns_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    # Dlya sebya: fallback, kogda frame ne verРЅСѓР» file/input_file kolonki.
    out: List[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            name = str(key or "").strip()
            if not name or name.lower() == "uuid":
                continue
            marker = name.lower()
            if marker in seen:
                continue
            name_looks_file = any(token in marker for token in ("file", "С„Р°Р№Р»", "С„РѕС‚Рѕ", "РёР·Р»СѓС‡"))
            # В fallback не считаем произвольные строки "файлом",
            # иначе можно выбрать текстовую колонку (например "Код классификатора").
            value_looks_file = isinstance(value, (list, dict)) and _has_visible_file_value(value)
            if not (name_looks_file or value_looks_file):
                continue
            seen.add(marker)
            out.append(name)
    return out


def _pick_best_file_column(candidates: List[str], rows: List[Dict[str, Any]]) -> Optional[str]:
    if not candidates:
        return None
    for col in candidates:
        for row in rows:
            if not isinstance(row, dict):
                continue
            if col in row and _has_visible_file_value(row.get(col)):
                return col
    return candidates[0]


def _resolve_column_name_case_insensitive(column_name: str, available: List[str]) -> Optional[str]:
    # Dlya sebya: normalizuem registr kolonki po real'nomu imeni iz frame.
    requested = str(column_name or "").strip()
    if not requested:
        return None
    if requested in available:
        return requested
    lowered = requested.lower()
    matches = [name for name in available if str(name).strip().lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    # Relaxed fallback: ignore spaces/underscores/hyphens.
    def _canon(value: str) -> str:
        return re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())

    requested_canon = _canon(requested)
    if requested_canon:
        relaxed = [name for name in available if _canon(str(name)) == requested_canon]
        if len(relaxed) == 1:
            return relaxed[0]
    return None


def _has_visible_file_value(value: Any) -> bool:
    # Dlya sebya: proverka, chto v kolonke est' ne pustoe failovoe znachenie.
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        lower = text.lower()
        if "С„Р°Р№Р» РЅРµ РЅР°Р№РґРµРЅ" in lower or "file not found" in lower:
            return False
        return True
    if isinstance(value, list):
        return any(_has_visible_file_value(item) for item in value)
    if isinstance(value, dict):
        if _has_downloadable_file_payload(value):
            return True
        for key in (
            "path",
            "file_path",
            "filename",
            "name",
            "data_base64",
            "content_base64",
            "base64",
            "data",
            "value",
        ):
            if key in value and _has_visible_file_value(value.get(key)):
                return True
        return False
    return True


def _short_preview(value: Any, *, max_len: int = 220) -> str:
    # Dlya sebya: bezopasnyy preview znacheniya dlya detail error.
    try:
        rendered = repr(value)
    except Exception:
        rendered = str(value)
    if len(rendered) > max_len:
        return rendered[: max_len - 3] + "..."
    return rendered


async def _query_frame_columns(dict_name: str) -> Dict[str, Any]:
    # Dlya sebya: poluchaem real'nye imena kolonok i failovyh kolonok iz query_frame.
    xml_body = user_dict_xml.build_query_user_dict_frame_xml(dict_name)
    resp, final_action = await _send_xml(
        "query_user_dict_frame",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    compact = _compact_query_frame_response(dict_name=dict_name, result=result, run_id=0)
    frames = compact.get("frames", [])
    if not isinstance(frames, list):
        frames = []
    all_columns: List[str] = []
    seen: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        cols = frame.get("columns")
        if not isinstance(cols, list):
            continue
        for col in cols:
            if not isinstance(col, dict):
                continue
            name = str(col.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            all_columns.append(name)
    file_columns = _extract_file_columns_from_frames(frames)
    return {"columns": all_columns, "file_columns": file_columns}


async def _query_row_by_uuid(
    dict_name: str,
    row_id: str,
    *,
    include_select_fallback: bool = True,
) -> Dict[str, Any]:
    # Dlya sebya: berem tekushchee znachenie stroki dlya post-verification upload.
    row_from_query: Optional[Dict[str, Any]] = None
    xml_body = user_dict_xml.build_query_single_user_dict_xml(
        dict_name,
        [{"column": "uuid", "value": row_id}],
    )
    try:
        resp, final_action = await _send_xml(
            "query_single_user_dict",
            xml_body,
            accept_action=True,
            capture_final_action=True,
        )
        result = _result(resp)
        _attach_action_payload(result, final_action)
        compact = _compact_search_response(
            dict_name=dict_name,
            result=result | {"request_xml": xml_body, "run_id": 0},
            run_id=0,
        )
        rows = compact.get("rows", [])
        if isinstance(rows, list) and rows:
            for row in rows:
                if isinstance(row, dict) and str(row.get("uuid", "")).strip() == row_id:
                    row_from_query = row
                    break
    except HTTPException:
        row_from_query = None

    # Fallback: na chasti sborok query_single/query_user_dict mogut "rezat'" failovye payload РёР·-Р·Р° С€Р°Р±Р»РѕРЅР°.
    # Probuyem select_fields СЃ С„РёР»СЊС‚СЂРѕРј РїРѕ uuid Рё, РїСЂРё СѓСЃРїРµС…Рµ, РёСЃРїРѕР»СЊР·СѓРµРј/РґРѕРїРѕР»РЅСЏРµРј СЃС‚СЂРѕРєСѓ РѕС‚С‚СѓРґР°.
    row_from_select: Optional[Dict[str, Any]] = None
    if include_select_fallback:
        try:
            full = await _send_select_fields_with_fallback(
                dict_name=dict_name,
                filters=[{"column": "uuid", "condition": DEFAULT_FILTER_CONDITION, "value": row_id}],
                order_by=[{"column": "uuid", "direction": DEFAULT_ORDER_DIRECTION}],
                limit=1,
                offset=0,
                expand_links=False,
                retry_uuid=row_id,
            )
            compact_select = _compact_select_fields_response(
                dict_name=dict_name,
                result=full,
                run_id=0,
            )
            rows_select = compact_select.get("rows", [])
            if isinstance(rows_select, list) and rows_select:
                for row in rows_select:
                    if isinstance(row, dict) and str(row.get("uuid", "")).strip() == row_id:
                        row_from_select = row
                        break
        except HTTPException:
            row_from_select = None

    if isinstance(row_from_query, dict) and isinstance(row_from_select, dict):
        merged = dict(row_from_query)
        for key, value in row_from_select.items():
            if key not in merged or not _has_visible_file_value(merged.get(key)):
                merged[key] = value
        return merged
    if isinstance(row_from_query, dict):
        return row_from_query
    if isinstance(row_from_select, dict):
        return row_from_select
    raise HTTPException(status_code=404, detail="Row not found by provided row_id.")


async def _query_row_by_uuid_from_full_query(
    dict_name: str,
    row_id: str,
) -> Optional[Dict[str, Any]]:
    # Dlya sebya: fallback dlya system dicts, kogda single/select ne vozvrashchaet failovye payload.
    for prefer_v2 in (True, False):
        xml_body = user_dict_xml.build_query_user_dict_xml(dict_name, prefer_v2=prefer_v2)
        try:
            full = await _execute_xml_operation(
                alias_fallback="query_user_dict",
                xml_body=xml_body,
                operation="query_user_dict_full_row_fallback",
                require_completed=True,
                final_action_timeout=INTERACTIVE_FINAL_ACTION_TIMEOUT_SEC,
                wait_non_system_response=False,
            )
        except HTTPException:
            continue
        compact = _compact_query_response(
            dict_name=dict_name,
            result=full,
            run_id=0,
            operation="query",
        )
        rows = compact.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("uuid") or "").strip() == row_id:
                return row
    return None


def _extract_uuid_candidates_from_db_value(value: Any) -> List[str]:
    # Dlya sebya: vynimaem UUID ssylki na files iz znacheniya kolonki user_table.
    out: List[str] = []
    seen: set[str] = set()

    def _add_uuid(raw: Any) -> None:
        for normalized in _extract_uuid_tokens_from_text(raw):
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, uuid.UUID):
            _add_uuid(node)
            return
        if isinstance(node, str):
            _add_uuid(node)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            for key in (
                "id",
                "uuid",
                "file_id",
                "value",
                "values",
                "items",
                "files",
                "file",
            ):
                if key in node:
                    _walk(node.get(key))
            for value in node.values():
                _walk(value)

    _walk(value)
    return out


def _extract_ai_id_candidates_from_value(value: Any) -> List[str]:
    # Dlya sebya: vynimaem ai_id iz file payload dlya fallback po documents.files.ai_id.
    out: List[str] = []
    seen: set[str] = set()

    def _add_ai_id(raw: Any) -> None:
        for normalized in _extract_uuid_tokens_from_text(raw):
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, uuid.UUID):
            _add_ai_id(node)
            return
        if isinstance(node, str):
            _add_ai_id(node)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            for key in ("ai_id", "id", "uuid", "file_id", "value", "values", "items", "files", "file"):
                if key in node:
                    _walk(node.get(key))
            for child in node.values():
                _walk(child)

    _walk(value)
    return out


async def _fetch_file_blob_by_file_id_from_paragraph_db(
    paragraph_session: AsyncSession,
    *,
    file_id: uuid.UUID,
    fallback_name: str,
) -> Dict[str, Any]:
    file_sql = text(
        """
        SELECT
            id,
            name,
            path,
            bytes AS bytes_oid,
            in_file_system
        FROM documents.files
        WHERE id = :file_id
        """
    )
    file_res = await paragraph_session.execute(file_sql, {"file_id": file_id})
    file_row = file_res.mappings().first()
    if file_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"DB fallback: file id '{file_id}' not found in documents.files.",
        )

    file_data: Optional[bytes] = None
    file_path = str(file_row.get("path") or "").strip()
    in_file_system = bool(file_row.get("in_file_system"))
    if file_path and in_file_system:
        try:
            with open(file_path, "rb") as fh:
                file_data = fh.read()
        except FileNotFoundError:
            file_data = None

    if file_data is None and file_row.get("bytes_oid") is not None:
        lo_sql = text("SELECT lo_get(:oid) AS data")
        lo_res = await paragraph_session.execute(lo_sql, {"oid": int(file_row.get("bytes_oid"))})
        lo_row = lo_res.mappings().first()
        if lo_row is not None and lo_row.get("data") is not None:
            file_data = bytes(lo_row.get("data"))

    if file_data is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"DB fallback: binary payload for file id '{file_id}' not found "
                "(neither file path nor large object bytes)."
            ),
        )

    resolved_name = (
        str(file_row.get("name") or "").strip()
        or os.path.basename(file_path)
        or fallback_name
    )
    return {
        "bytes": file_data,
        "filename": resolved_name,
        "source": "paragraph_db",
        "file_id": str(file_id),
    }


async def _download_file_blob_from_paragraph_db(
    *,
    dict_name: str,
    row_id: str,
    column_name: str,
    file_index: int = 0,
) -> Dict[str, Any]:
    # Dlya sebya: fallback СЃРєР°С‡РёРІР°РЅРёСЏ С„Р°Р№Р»Р° РЅР°РїСЂСЏРјСѓСЋ РёР· Paragraph DB (РµСЃР»Рё ISHD payload РїСѓСЃС‚РѕР№).
    runtime_target = _target_ctx.get()
    dsn = ((runtime_target.paragraph_db_dsn if runtime_target else None) or settings.paragraph_db_dsn or "").strip()
    if not dsn:
        raise HTTPException(
            status_code=400,
            detail="Paragraph DB DSN is not configured for selected target and .env fallback",
        )

    maker = get_paragraph_sessionmaker_by_dsn(dsn)
    row_uuid = uuid.UUID(str(row_id).strip("{}"))
    idx = max(0, int(file_index or 0))

    async with maker() as paragraph_session:
        dict_name_candidates: List[str] = []
        for raw_name in (dict_name, str(dict_name or "").split(".")[-1].strip()):
            nm = str(raw_name or "").strip()
            if nm and nm not in dict_name_candidates:
                dict_name_candidates.append(nm)
        with suppress(HTTPException):
            frame_xml = user_dict_xml.build_query_user_dict_frame_xml(dict_name)
            frame_full = await _execute_xml_operation(
                alias_fallback="query_user_dict_frame",
                xml_body=frame_xml,
                operation="db_fallback_query_frame_resolve",
                require_completed=True,
                final_action_timeout=INTERACTIVE_FINAL_ACTION_TIMEOUT_SEC,
                wait_non_system_response=False,
            )
            effective_name = _resolve_effective_dict_name_from_query_frame(
                action_data=frame_full.get("action_data"),
                requested_name=dict_name,
            )
            if effective_name:
                for raw_name in (effective_name, str(effective_name).split(".")[-1].strip()):
                    nm = str(raw_name or "").strip()
                    if nm and nm not in dict_name_candidates:
                        dict_name_candidates.append(nm)

        dict_meta_sql = text(
            """
            SELECT
                t.id AS table_id,
                t.counter AS table_counter,
                c.column_number AS column_number,
                c.type AS column_type
            FROM user_dictionaries.user_tables t
            JOIN user_dictionaries.user_table_columns c
              ON c.id_user_table = t.id
            WHERE lower(t.name) = lower(:dict_name)
              AND lower(c.name) = lower(:column_name)
            ORDER BY c."order" NULLS LAST, c.column_number NULLS LAST
            LIMIT 1
            """
        )
        dict_meta = None
        matched_dict_name = None
        for name_candidate in dict_name_candidates:
            dict_meta_res = await paragraph_session.execute(
                dict_meta_sql,
                {"dict_name": name_candidate, "column_name": column_name},
            )
            dict_meta = dict_meta_res.mappings().first()
            if dict_meta is not None:
                matched_dict_name = name_candidate
                break
        if dict_meta is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"DB fallback: dictionary '{dict_name}' or column '{column_name}' not found in user_dictionaries metadata. "
                    f"tried_names={dict_name_candidates}"
                ),
            )

        table_counter = dict_meta.get("table_counter")
        column_number = dict_meta.get("column_number")
        if table_counter is None or column_number is None:
            raise HTTPException(
                status_code=409,
                detail="DB fallback: cannot resolve physical user_table/column mapping for requested dictionary column.",
            )

        try:
            table_counter_int = int(table_counter)
            column_number_int = int(column_number)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=409,
                detail="DB fallback: invalid table/column mapping in user_dictionaries metadata.",
            )

        if table_counter_int <= 0 or column_number_int <= 0:
            raise HTTPException(
                status_code=409,
                detail="DB fallback: table/column mapping points to non-positive identifiers.",
            )

        table_ident = f"user_dictionaries.user_table{table_counter_int}"
        column_ident = f"column{column_number_int}"

        row_sql = text(
            f"""
            SELECT id, "{column_ident}" AS file_ref
            FROM {table_ident}
            WHERE id = :row_id
            LIMIT 1
            """
        )
        row_res = await paragraph_session.execute(row_sql, {"row_id": row_uuid})
        row_db = row_res.mappings().first()
        if row_db is None:
            raise HTTPException(
                status_code=404,
                detail=f"DB fallback: row_id '{row_id}' not found in {table_ident}.",
            )

        file_ids = _extract_uuid_candidates_from_db_value(row_db.get("file_ref"))
        if not file_ids:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"DB fallback: column '{column_name}' in row '{row_id}' does not contain a file UUID reference. "
                    f"Raw value: {_short_preview(row_db.get('file_ref'))}"
                ),
            )
        if idx >= len(file_ids):
            raise HTTPException(
                status_code=404,
                detail=f"DB fallback: file_index={idx} is out of range (available: {len(file_ids)}).",
            )

        selected_file_id = uuid.UUID(file_ids[idx])
        blob = await _fetch_file_blob_by_file_id_from_paragraph_db(
            paragraph_session,
            file_id=selected_file_id,
            fallback_name=f"{dict_name}_{column_name}_{selected_file_id}.bin",
        )
        if matched_dict_name:
            blob["dict_name_matched"] = matched_dict_name
        blob["column_number"] = column_number_int
        blob["column_type"] = dict_meta.get("column_type")
        return blob


async def _download_file_blob_from_paragraph_db_by_ai_id(
    *,
    row_value: Any,
    dict_name: str,
    column_name: str,
    file_index: int = 0,
) -> Dict[str, Any]:
    # Dlya sebya: fallback dlya sistemnyh slovarey, gde v payload est' ai_id, a bytes v documents.files.
    runtime_target = _target_ctx.get()
    dsn = ((runtime_target.paragraph_db_dsn if runtime_target else None) or settings.paragraph_db_dsn or "").strip()
    if not dsn:
        raise HTTPException(
            status_code=400,
            detail="Paragraph DB DSN is not configured for selected target and .env fallback",
        )

    ai_ids = _extract_ai_id_candidates_from_value(row_value)
    if not ai_ids:
        raise HTTPException(
            status_code=404,
            detail=(
                f"DB ai_id fallback: no ai_id found in value of column '{column_name}'. "
                f"Raw value: {_short_preview(row_value)}"
            ),
        )

    idx = max(0, int(file_index or 0))
    if idx >= len(ai_ids):
        raise HTTPException(
            status_code=404,
            detail=f"DB ai_id fallback: file_index={idx} is out of range (available ai_id count: {len(ai_ids)}).",
        )

    maker = get_paragraph_sessionmaker_by_dsn(dsn)
    async with maker() as paragraph_session:
        for ai_raw in ai_ids[idx:]:
            ai_uuid = uuid.UUID(ai_raw)
            by_ai_sql = text(
                """
                SELECT id
                FROM documents.files
                WHERE ai_id = :ai_id
                ORDER BY "timestamp" DESC NULLS LAST, id DESC
                LIMIT 1
                """
            )
            by_ai_res = await paragraph_session.execute(by_ai_sql, {"ai_id": ai_uuid})
            by_ai_row = by_ai_res.mappings().first()
            if by_ai_row is not None:
                file_id = by_ai_row.get("id")
                if file_id is not None:
                    blob = await _fetch_file_blob_by_file_id_from_paragraph_db(
                        paragraph_session,
                        file_id=uuid.UUID(str(file_id)),
                        fallback_name=f"{dict_name}_{column_name}_{ai_uuid}.bin",
                    )
                    blob["source"] = "paragraph_db_ai_id"
                    blob["ai_id"] = str(ai_uuid)
                    return blob

            # В некоторых сборках в payload `id` — это сразу documents.files.id, а не ai_id.
            try:
                blob = await _fetch_file_blob_by_file_id_from_paragraph_db(
                    paragraph_session,
                    file_id=ai_uuid,
                    fallback_name=f"{dict_name}_{column_name}_{ai_uuid}.bin",
                )
                blob["source"] = "paragraph_db_file_id_hint"
                blob["file_id_hint"] = str(ai_uuid)
                return blob
            except HTTPException:
                continue

    raise HTTPException(
        status_code=404,
        detail=(
            f"DB ai_id fallback: files not found by ai_id for '{dict_name}.{column_name}'. "
            f"ai_ids={ai_ids}"
        ),
    )


async def _download_file_blob_via_documentfilesget(
    *,
    file_ids: List[str],
    file_index: int = 0,
    max_id_variants: Optional[int] = None,
    per_request_timeout_sec: Optional[float] = None,
) -> Dict[str, Any]:
    # Dlya sebya: osnovnoy put' skachivaniya faila cherez XML documentfilesget.
    if not file_ids:
        raise HTTPException(status_code=400, detail="No file_id found for documentfilesget request.")

    idx = max(0, int(file_index or 0))
    if idx >= len(file_ids):
        raise HTTPException(
            status_code=400,
            detail=f"file_index out of range for file_id candidates: {idx} (available: {len(file_ids)}).",
        )

    def _docfiles_id_variants(ids: List[str]) -> List[List[str]]:
        variants: List[List[str]] = []
        seen_local: set[str] = set()
        for raw in ids:
            text_id = str(raw or "").strip()
            if not text_id:
                continue
            candidates: List[str] = [text_id]
            try:
                normalized = str(uuid.UUID(text_id.strip("{}")))
                candidates.extend(["{" + normalized + "}", normalized, f'data: "{{{normalized}}}"'])
            except ValueError:
                pass
            for c in candidates:
                key = c.strip()
                if not key or key in seen_local:
                    continue
                seen_local.add(key)
                variants.append([key])
        if not variants:
            variants.append(ids)
        return variants

    def _extract_docfiles_list(action_data: Any) -> List[Dict[str, Any]]:
        if not isinstance(action_data, dict):
            return []

        direct = action_data.get("files")
        if isinstance(direct, list):
            direct_items = [item for item in direct if isinstance(item, dict)]
            if direct_items:
                return direct_items

        found: List[Dict[str, Any]] = []

        def _walk(node: Any) -> None:
            nonlocal found
            if found:
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "files" and isinstance(value, list):
                        dict_items = [item for item in value if isinstance(item, dict)]
                        if dict_items:
                            found = dict_items
                            return
                    _walk(value)
                return
            if isinstance(node, list):
                dict_items = [item for item in node if isinstance(item, dict)]
                if dict_items and any("file" in item or "file_id" in item for item in dict_items):
                    found = dict_items
                    return
                for item in node:
                    _walk(item)

        _walk(action_data)
        return found

    files: List[Dict[str, Any]] = []
    last_error: Optional[HTTPException] = None
    variants = _docfiles_id_variants(file_ids)
    if isinstance(max_id_variants, int) and max_id_variants > 0:
        variants = variants[: max_id_variants]

    for ids_variant in variants:
        xml_body = user_dict_xml.build_documentfilesget_xml(ids_variant)
        try:
            coro = _execute_xml_operation(
                alias_fallback="documentfilesget",
                xml_body=xml_body,
                operation="documentfilesget",
                require_completed=True,
            )
            if per_request_timeout_sec and per_request_timeout_sec > 0:
                result = await asyncio.wait_for(coro, timeout=float(per_request_timeout_sec))
            else:
                result = await coro
        except HTTPException as exc:
            last_error = exc
            continue
        except asyncio.TimeoutError:
            last_error = HTTPException(
                status_code=504,
                detail=f"documentfilesget timeout after {per_request_timeout_sec}s",
            )
            continue
        action_data = result.get("action_data", {})
        files = _extract_docfiles_list(action_data)
        if files:
            break

    if not files:
        if last_error is not None:
            raise last_error
        raise HTTPException(status_code=404, detail="documentfilesget returned no files in action_data.files.")
    if idx >= len(files):
        raise HTTPException(
            status_code=404,
            detail=f"documentfilesget returned {len(files)} files, but file_index={idx}.",
        )

    selected = files[idx]
    file_payload = selected.get("file")
    if not isinstance(file_payload, dict):
        raise HTTPException(status_code=404, detail="documentfilesget returned file item without binary payload.")

    data_b64 = file_payload.get("data_base64")
    if not data_b64:
        raise HTTPException(status_code=404, detail="documentfilesget returned empty binary payload.")

    try:
        data = base64.b64decode(str(data_b64), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="documentfilesget returned invalid base64 payload.") from exc

    filename = str(file_payload.get("filename") or "").strip()
    if not filename:
        filename = str(selected.get("file_id") or file_ids[idx]).strip() + ".bin"

    return {
        "bytes": data,
        "filename": filename,
        "source": "documentfilesget",
        "file_id": str(selected.get("file_id") or file_ids[idx]),
    }


async def _wait_until_file_visible(
    *,
    dict_name: str,
    row_id: str,
    column_name: str,
    timeout_sec: float = UPLOAD_FILE_VERIFY_TIMEOUT_SEC,
    poll_sec: float = UPLOAD_FILE_VERIFY_POLL_SEC,
) -> Dict[str, Any]:
    # Dlya sebya: posle upload daem Paragraph vremya zapisat' fail i pereproveryaem stroku.
    started_at = datetime.now(timezone.utc).timestamp()
    last_value: Any = None
    last_available_columns: List[str] = []
    last_resolved_column: Optional[str] = None
    last_visible_other_file_columns: List[str] = []
    last_visible_other_file_previews: Dict[str, str] = {}
    checks = 0

    while True:
        checks += 1
        row_after = await _query_row_by_uuid(dict_name, row_id)
        available_columns = list(row_after.keys()) if isinstance(row_after, dict) else []
        last_available_columns = available_columns
        resolved_column = _resolve_column_name_case_insensitive(column_name, available_columns) or column_name
        last_resolved_column = resolved_column
        if isinstance(row_after, dict) and resolved_column in row_after:
            last_value = row_after.get(resolved_column)
            if _has_visible_file_value(last_value):
                return {
                    "ok": True,
                    "checks": checks,
                    "last_value": last_value,
                    "resolved_column": resolved_column,
                    "available_columns": available_columns,
                }
        if isinstance(row_after, dict):
            visible_other_file_columns: List[str] = []
            visible_other_file_previews: Dict[str, str] = {}
            for key, val in row_after.items():
                key_name = str(key or "").strip()
                if not key_name or key_name.lower() == "uuid":
                    continue
                if key_name == resolved_column:
                    continue
                if not _has_visible_file_value(val):
                    continue
                visible_other_file_columns.append(key_name)
                visible_other_file_previews[key_name] = _short_preview(val)
            last_visible_other_file_columns = visible_other_file_columns
            last_visible_other_file_previews = visible_other_file_previews

        elapsed = datetime.now(timezone.utc).timestamp() - started_at
        if elapsed >= float(timeout_sec):
            return {
                "ok": False,
                "checks": checks,
                "last_value": last_value,
                "resolved_column": last_resolved_column,
                "available_columns": last_available_columns,
                "visible_other_file_columns": last_visible_other_file_columns,
                "visible_other_file_previews": last_visible_other_file_previews,
            }

        await asyncio.sleep(max(0.1, float(poll_sec)))


def _row_id_variants(row_id: str) -> List[str]:
    # Dlya sebya: vspomogatelnyy shag dlya API (row id variants).
    value = str(row_id).strip()
    if not value:
        return []
    return [value]


def _normalize_uuid_or_raise(row_id: str) -> str:
    # Dlya sebya: vspomogatelnyy shag dlya API (normalize uuid or raise).
    value = str(row_id).strip()
    if not value:
        raise HTTPException(status_code=400, detail="row_id must not be empty")
    try:
        parsed = uuid.UUID(value.strip("{}"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=(
                "row_id must be UUID from /dicts/search row_ids "
                "(for example: {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx})"
            ),
        )
    return "{" + str(parsed) + "}"


def _action_items_to_map(action_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (action items to map).
    if not action_data:
        return {}
    data: Dict[str, Any] = {}
    for item in action_data.get("items", []):
        key = item.get("alias") or item.get("name") or f"item_{item.get('id')}"
        data[key] = item.get("value")
    return data


def _compact_search_response(
    *,
    dict_name: str,
    result: Dict[str, Any],
    run_id: int,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact search response).
    tables = result.get("tables", [])
    rows: List[Dict[str, Any]] = []
    columns: List[str] = []

    if tables:
        first_table = tables[0]
        rows_data = first_table.get("rows", [])
        if isinstance(rows_data, list):
            rows = [row for row in rows_data if isinstance(row, dict)]
        cols_data = first_table.get("columns", [])
        if isinstance(cols_data, list):
            for col in cols_data:
                if not isinstance(col, dict):
                    continue
                key = str(col.get("key", "")).strip()
                if key:
                    columns.append(key)

    row_ids: List[str] = []
    for row in rows:
        row_id = str(row.get("uuid", "")).strip()
        if row_id:
            row_ids.append(row_id)

    return {
        "status": result["status"],
        "report_code_name": result["report_code_name"],
        "description": result["description"],
        "dict_name": dict_name,
        "found_count": result.get("found_count", 0),
        "columns": columns,
        "row_ids": row_ids,
        "rows": rows,
        "run_id": run_id,
    }


def _normalize_column_type(column_type: Any) -> str:
    # Dlya sebya: vspomogatelnyy shag dlya API (normalize column type).
    if isinstance(column_type, str):
        return _repair_mojibake_text(column_type).strip().lower()
    if isinstance(column_type, list):
        for item in column_type:
            if isinstance(item, str) and item.strip():
                return _repair_mojibake_text(item).strip().lower()
    return ""


def _extract_select_field_value(value: Any, column_type: str, group_link: Any = None) -> Any:
    # Parsed payload from select_fields_user_dict often contains 4 variants
    # (text/int/double/bool) under one alias "value". Use column type to pick
    # the intended one and avoid returning template defaults.
    # Dlya sebya: vspomogatelnyy shag dlya API (extract select field value).
    if isinstance(value, list):
        text_val = value[0] if len(value) > 0 else None
        int_val = value[1] if len(value) > 1 else None
        double_val = value[2] if len(value) > 2 else None
        bool_val = value[3] if len(value) > 3 else None

        if "С†РµР»РѕС‡РёСЃР»РµРЅ" in column_type:
            return int_val
        if "РґСЂРѕР±РЅ" in column_type:
            return double_val
        if "С„Р»Р°Рі" in column_type:
            return bool(bool_val)
        if "СЃСЃС‹Р»РєР°" in column_type and isinstance(group_link, dict):
            row_id = str(group_link.get("row_id", "")).strip()
            if row_id:
                return group_link

        if isinstance(text_val, str) and text_val.strip():
            return text_val

        # Fallback: first non-empty/non-default value.
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    return item
                continue
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                if item != 0:
                    return item
                continue
            if item not in (None, "", [], {}):
                return item
        return None

    if isinstance(value, str):
        return value if value.strip() else None
    return value


def _compact_select_fields_response(
    *,
    dict_name: str,
    result: Dict[str, Any],
    run_id: int,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact select fields response).
    rows_raw = result.get("action_data", {}).get("table_rows", [])
    rows: List[Dict[str, Any]] = []
    columns: List[str] = []
    row_ids: List[str] = []

    if isinstance(rows_raw, list):
        for raw_row in rows_raw:
            if not isinstance(raw_row, dict):
                continue
            raw_columns = raw_row.get("table_columns", [])
            if not isinstance(raw_columns, list):
                continue

            row: Dict[str, Any] = {}
            for raw_col in raw_columns:
                if not isinstance(raw_col, dict):
                    continue
                name = str(raw_col.get("column_name", "")).strip()
                if not name:
                    continue
                column_type = _normalize_column_type(raw_col.get("column_type"))
                value = _extract_select_field_value(
                    raw_col.get("value"),
                    column_type,
                    raw_col.get("group_link"),
                )
                row[name] = value
                if name not in columns:
                    columns.append(name)

            if row:
                row_uuid = str(row.get("uuid", "")).strip()
                if row_uuid:
                    row_ids.append(row_uuid)
                rows.append(row)

    return {
        "status": result["status"],
        "report_code_name": result["report_code_name"],
        "description": result["description"],
        "dict_name": dict_name,
        "found_count": len(rows),
        "columns": columns,
        "row_ids": row_ids,
        "rows": rows,
        "run_id": run_id,
    }


def _compact_status_response(
    *,
    operation: str,
    dict_name: Optional[str],
    result: Dict[str, Any],
    run_id: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact status response).
    payload: Dict[str, Any] = {
        "status": result.get("status"),
        "report_code_name": result.get("report_code_name"),
        "description": result.get("description", ""),
        "operation": operation,
        "dict_name": dict_name,
        "run_id": run_id,
    }
    final_state = str(result.get("final_state", "")).strip()
    if final_state:
        payload["final_state"] = final_state
    if extra:
        payload.update(extra)
    return payload


def _compact_query_response(
    *,
    dict_name: Optional[str],
    result: Dict[str, Any],
    run_id: int,
    operation: str,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact query response).
    tables = result.get("tables", [])
    first_rows: List[Dict[str, Any]] = []
    first_columns: List[str] = []

    if tables:
        first = tables[0]
        rows_data = first.get("rows", [])
        if isinstance(rows_data, list):
            first_rows = [row for row in rows_data if isinstance(row, dict)]
        cols_data = first.get("columns", [])
        if isinstance(cols_data, list):
            first_columns = [
                str(c.get("key", "")).strip()
                for c in cols_data
                if isinstance(c, dict) and str(c.get("key", "")).strip()
            ]

    return _compact_status_response(
        operation=operation,
        dict_name=dict_name,
        result=result,
        run_id=run_id,
        extra={
            "found_count": int(result.get("found_count", 0) or 0),
            "tables_count": len(tables) if isinstance(tables, list) else 0,
            "columns": first_columns,
            "row_ids": _extract_row_ids_from_tables(tables) if isinstance(tables, list) else [],
            "rows": first_rows,
        },
    )


def _compact_metainfo_response(
    *,
    dict_name: str,
    result: Dict[str, Any],
    run_id: int,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact metainfo response).
    action_data = result.get("action_data", {})
    if not isinstance(action_data, dict):
        action_data = {}
    dict_id = action_data.get("dict_id")
    dict_name_value = action_data.get("dict_name")
    dict_size = action_data.get("dict_size")
    dict_last_modified = action_data.get("dict_last_modified")

    if dict_id is None:
        dict_id = result.get("dict_id")
    if dict_name_value is None:
        dict_name_value = result.get("dict_name_value") or result.get("dict_name")
    if dict_size is None:
        dict_size = result.get("dict_size")
    if dict_last_modified is None:
        dict_last_modified = result.get("dict_last_modified")
    return _compact_status_response(
        operation="metainfo",
        dict_name=dict_name,
        result=result,
        run_id=run_id,
        extra={
            "dict_id": dict_id,
            "dict_name_value": dict_name_value,
            "dict_size": dict_size,
            "dict_last_modified": dict_last_modified,
        },
    )


def _compact_query_frame_response(
    *,
    dict_name: Optional[str],
    result: Dict[str, Any],
    run_id: int,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (compact query frame response).
    action_data = result.get("action_data", {})
    frames_raw = action_data.get("user_table_frame", []) if isinstance(action_data, dict) else []
    frames: List[Dict[str, Any]] = []
    if isinstance(frames_raw, list):
        for raw in frames_raw:
            if not isinstance(raw, dict):
                continue
            columns: List[Dict[str, Any]] = []
            raw_columns = raw.get("ut_column_frame", [])
            if isinstance(raw_columns, list):
                for col in raw_columns:
                    if not isinstance(col, dict):
                        continue
                    col_name = str(col.get("utc_name", "")).strip()
                    if not col_name:
                        continue
                    columns.append(
                        {
                            "name": col_name,
                            "type": col.get("utc_type"),
                        }
                    )
            frame_name = str(raw.get("ut_name", "")).strip()
            frame_name_real = str(raw.get("ut_name_real", "")).strip()
            frame_id = str(raw.get("ut_id_uuid", "")).strip()
            if frame_name or frame_name_real or frame_id or columns:
                frames.append(
                    {
                        "name": frame_name or frame_name_real or None,
                        "name_real": frame_name_real or None,
                        "id": frame_id or None,
                        "columns": columns,
                    }
                )
    return _compact_status_response(
        operation="query_frame",
        dict_name=dict_name,
        result=result,
        run_id=run_id,
        extra={
            "frames_count": len(frames),
            "frames": frames,
        },
    )


def _attach_action_payload(
    result: Dict[str, Any],
    final_action: Optional[Ai_Documents_pb2.SendActionRequest],
) -> None:
    # Dlya sebya: vspomogatelnyy shag dlya API (attach action payload).
    action_data = _action_request_to_python(final_action)
    if not action_data:
        return

    result["final_action"] = action_data
    result["action_data"] = _action_items_to_map(action_data)
    result["final_state"] = (action_data.get("state") or "").lower()

    if result["final_state"] == "failed":
        result["status"] = "fail"
        reason = result["action_data"].get("reason")
        if isinstance(reason, str) and reason.strip():
            result["description"] = reason.strip()

    tables = _collect_tables(result["action_data"])
    result["tables"] = tables
    result["found_count"] = sum(len(t.get("rows", [])) for t in tables)


def _resolve_effective_dict_name_from_query_frame(
    *,
    action_data: Any,
    requested_name: str,
) -> Optional[str]:
    # Dlya sebya: v raznyh sborkah nuzhno korrektno vybrat' kanonicheskoe imya
    # (ut_name_real), chtoby metainfo/query/select_fields rabotali stabil'no.
    if not isinstance(action_data, dict):
        return None
    frames = action_data.get("user_table_frame")
    if not isinstance(frames, list):
        return None

    requested = requested_name.strip()
    if not requested:
        return None
    requested_lower = requested.lower()

    exact_real: Optional[str] = None
    exact_short: Optional[str] = None
    suffix_real: Optional[str] = None
    suffix_short: Optional[str] = None

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        short_name = str(frame.get("ut_name") or "").strip()
        real_name = str(frame.get("ut_name_real") or "").strip()

        if real_name and real_name.lower() == requested_lower:
            exact_real = real_name
            break
        if short_name and short_name.lower() == requested_lower:
            exact_short = short_name

        if real_name and (
            requested_lower.endswith(real_name.lower())
            or real_name.lower().endswith(requested_lower)
        ):
            suffix_real = suffix_real or real_name
        if short_name and (
            requested_lower.endswith(short_name.lower())
            or short_name.lower().endswith(requested_lower)
        ):
            suffix_short = suffix_short or short_name

    if exact_real:
        return exact_real
    if exact_short:
        return exact_short
    if suffix_real:
        return suffix_real
    if suffix_short:
        # If requested name is qualified (group.path), keep requested
        # and do not downgrade to short name from frame.
        if "." in requested or "/" in requested or "\\" in requested:
            return requested
        return suffix_short
    return None


def _require_completed_final_state(result: Dict[str, Any], *, operation: str) -> None:
    # Dlya sebya: dlya mutating endpointov schitaem uspeshnym tolko final_state=completed.
    if result.get("status") != "ok":
        return

    final_state = str(result.get("final_state", "")).strip().lower()
    if not final_state:
        result["status"] = "fail"
        if not str(result.get("description", "")).strip():
            result["description"] = (
                f"{operation}: no final workflow state from Paragraph "
                "(transport ACK received, business result unknown)"
            )
        return

    if final_state != "completed":
        result["status"] = "fail"
        if not str(result.get("description", "")).strip():
            result["description"] = f"{operation}: final_state={final_state}"


def _extract_insert_error_column(description: str) -> Optional[str]:
    # Dlya sebya: izvlekaem imya kolonki iz tipovoy oshibki insert.
    text = str(description or "")
    if not text:
        return None
    m = _INSERT_COLUMN_NAME_RE.search(text)
    if not m:
        return None
    value = str(m.group(1) or "").strip()
    return value or None


def _enhance_insert_type_mismatch_description(result: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    # Dlya sebya: dobavlyaem ponyatnuyu podskazku dlya konfliktov tipov v insert.
    if str(result.get("status", "")).strip().lower() != "fail":
        return

    description = str(result.get("description", "")).strip()
    if "OneOfParameters_Type" not in description or "ColumnTypes" not in description:
        return

    column_name = _extract_insert_error_column(description)
    if not column_name:
        return

    sample_value: Any = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if column_name in row:
            sample_value = row.get(column_name)
            break

    value_repr = repr(sample_value) if sample_value is not None else "<empty>"
    value_type = type(sample_value).__name__ if sample_value is not None else "none"
    hint = (
        f" РџРѕРґСЃРєР°Р·РєР°: РєРѕР»РѕРЅРєР° '{column_name}' РѕР¶РёРґР°РµС‚ С‚РёРї РёР· СЃС…РµРјС‹ СЃРїСЂР°РІРѕС‡РЅРёРєР°, "
        f"РЅРѕ РїРµСЂРµРґР°РЅРѕ {value_repr} (type={value_type}). Р”Р»СЏ uuid РїРµСЂРµРґР°РІР°Р№С‚Рµ СЃС‚СЂРѕРєСѓ UUID."
    )
    if hint not in description:
        result["description"] = description + hint


async def _send_xml(
    alias_fallback: str,
    xml_body: str,
    *,
    accept_action: bool = True,
    capture_final_action: bool = False,
    final_action_timeout: Optional[float] = None,
    wait_non_system_response: bool = True,
):
    # Dlya sebya: vspomogatelnyy shag dlya API (send xml).
    if _target_client_ctx.get() is not None:
        client = _target_client_ctx.get()
    else:
        try:
            client = get_ishd_client()
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Default ISHD client is not initialized. "
                    "Select target_id in UI/API or configure reachable .env ISHD."
                ),
            ) from e
    effective_final_action_timeout = (
        float(final_action_timeout)
        if final_action_timeout is not None
        else INTERACTIVE_FINAL_ACTION_TIMEOUT_SEC
    )
    try:
        await client.ensure_connected()
        return await client.send_paragraph_xml(
            alias=_xml_alias(xml_body) or alias_fallback,
            xml_body=xml_body,
            accept_action=accept_action,
            capture_final_action=capture_final_action,
            final_action_timeout=effective_final_action_timeout,
            wait_non_system_response=wait_non_system_response,
        )
    except IshdError as e:
        raise HTTPException(status_code=502, detail=f"ISHD error: {e}")
    except (ConnectionError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"ISHD transport error: {e}")


async def _log_single_run(
    session: AsyncSession,
    *,
    run_name: str,
    xml_body: str,
    result: Dict[str, Any],
) -> int:
    # Dlya sebya: vspomogatelnyy shag dlya API (log single run).
    run_id = await test_run_logger.create_run(session, run_name)
    await test_run_logger.log_step(
        session,
        run_id,
        1,
        request=xml_body,
        response=result,
        status=result["status"],
        message=result["description"],
    )
    await test_run_logger.finish_run(
        session, run_id, "success" if result["status"] == "ok" else "failed"
    )
    await session.commit()
    return run_id


async def _run_and_log(
    session: AsyncSession,
    run_id: int,
    step_number: int,
    *,
    title: str,
    alias: str,
    xml_body: str,
    accept_action: bool = True,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (run and log).
    resp = await _send_xml(alias, xml_body, accept_action=accept_action)
    result = _result(resp)
    await test_run_logger.log_step(
        session,
        run_id,
        step_number,
        request=xml_body,
        response=result,
        status=result["status"],
        message=f"{title}: {result['description'] or ''}".strip(),
    )
    return result


def _utc_now_iso() -> str:
    # Dlya sebya: chtoby v otchete vse vremya bylo v odnom formate UTC.
    return datetime.now(timezone.utc).isoformat()


def _current_target_name() -> str:
    target = _target_ctx.get()
    if target is None:
        return "env-default"
    return target.name


def _current_target_id() -> Optional[int]:
    target = _target_ctx.get()
    if target is None:
        return None
    return target.id


def _safe_name_token(raw: str, *, max_len: int = 24) -> str:
    # Dlya sebya: iz nazvaniya spravochnika sobiraem bezopasnyy kusok dlya temp-imeni.
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(raw))
    cleaned = cleaned.strip("_").lower() or "dict"
    return cleaned[:max_len]


def _build_autotest_run_id() -> str:
    # Dlya sebya: korotkiy i chitabelnyy id progonР В°.
    return "ud_auto_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _build_temp_dict_name(prefix: str, source_dict_name: str, suffix: str) -> str:
    # Dlya sebya: vse vremennye spravochniki pomРµС‡Р°РµРј prРµС„РёРєСЃРѕРј, chtoby ih legko bylo nayti.
    safe_prefix = _safe_name_token(prefix, max_len=16)
    safe_source = _safe_name_token(source_dict_name, max_len=20)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"{safe_prefix}_{safe_source}_{suffix}_{stamp}"


def _make_all_types_columns(source_dict_name: str) -> List[Dict[str, Any]]:
    # Dlya sebya: smoke-nabor kolonok po vsem tipam iz create_user_dict_v1.
    columns: List[Dict[str, Any]] = []
    for item in user_dict_xml.get_column_type_help():
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        column: Dict[str, Any] = {
            "name": f"c_{key}",
            "type": key,
            "required": False,
        }
        if key == "link":
            # Dlya link podstavlyaem ssylku na proveryaemyy spravochnik.
            column["ref_dict"] = source_dict_name
            column["ref_column"] = "uuid"
            column["cascade"] = False
        columns.append(column)
    return columns


def _extract_dict_refs(raw: Any) -> List[Dict[str, str]]:
    # Dlya sebya: REST list byvaet v raznom vide, poetomu akuratno sobiraem uid+name iz lyuboy struktury.
    # Р’ РїСЂРёРѕСЂРёС‚РµС‚Рµ СЃС‚СЂРѕРіРёР№ СЂР°Р·Р±РѕСЂ /api/v1/meta/u_dict/:
    # Р±РµСЂРµРј С‚РѕР»СЊРєРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ СЃРїСЂР°РІРѕС‡РЅРёРєРё (type=0) Рё РѕР±С‹С‡РЅС‹Рµ (visible=0),
    # С‡С‚РѕР±С‹ СЃРїРёСЃРѕРє СЃРѕРІРїР°РґР°Р» СЃ РІРєР»Р°РґРєРѕР№ "РџРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ СЃРїСЂР°РІРѕС‡РЅРёРєРё" РІ UI РџР°СЂР°РіСЂР°С„Р°.
    if isinstance(raw, list):
        strict: List[Dict[str, str]] = []
        seen_strict: set[str] = set()
        for node in raw:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "").strip()
            uid = str(node.get("uid") or node.get("id") or "").strip()
            if not name:
                continue
            dict_type = node.get("type")
            visible = node.get("visible")
            if dict_type not in (0, "0", None):
                continue
            if visible not in (0, "0", None):
                continue
            key = f"{uid}|{name}".lower()
            if key in seen_strict:
                continue
            seen_strict.add(key)
            strict.append({"name": name, "uid": uid})
        if strict:
            strict.sort(key=lambda x: x["name"].lower())
            return strict

    found: List[Dict[str, str]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = str(
                node.get("name")
                or node.get("title")
                or node.get("dict_name")
                or node.get("user_table_name")
                or ""
            ).strip()
            uid = str(
                node.get("uid")
                or node.get("table_uid")
                or node.get("id")
                or node.get("uuid")
                or ""
            ).strip()
            if name:
                key = f"{uid}|{name}".lower()
                if key not in seen:
                    seen.add(key)
                    found.append({"name": name, "uid": uid})
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(raw)
    found.sort(key=lambda x: x["name"].lower())
    return found


def _extract_dict_refs_from_query_action(action_data: Any) -> List[Dict[str, str]]:
    # Dlya sebya: fallback-spisok spravochnikov iz ISHD query_user_dict (action_data.user_tables).
    if not isinstance(action_data, dict):
        return []

    user_tables = action_data.get("user_tables")
    if not isinstance(user_tables, list):
        return []

    found: List[Dict[str, str]] = []
    seen: set[str] = set()

    for node in user_tables:
        if not isinstance(node, dict):
            continue

        name = str(node.get("_name") or node.get("name") or "").strip()
        uid = str(node.get("uid") or node.get("id") or node.get("_id") or "").strip()

        if not name:
            for key, value in node.items():
                if str(key).startswith("_"):
                    continue
                if isinstance(value, dict) and ("columns" in value or "rows" in value):
                    name = str(key).strip()
                    break

        if not name:
            continue

        marker = f"{uid}|{name}".lower()
        if marker in seen:
            continue
        seen.add(marker)
        found.append({"name": name, "uid": uid})

    if not found:
        # Dlya sebya: na nekotoryh sborkakh query_user_dict mozhet prislat netipovuyu formu.
        # Probuem obobschennyy razbor action_data, chtoby ne poteryat spisok.
        generic = _extract_dict_refs(action_data)
        for item in generic:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if _repair_mojibake_text(name).lower().startswith("СЃС‚РѕР»Р±РµС†"):
                continue
            uid = str(item.get("uid") or "").strip()
            marker = f"{uid}|{name}".lower()
            if marker in seen:
                continue
            seen.add(marker)
            found.append({"name": name, "uid": uid})

    found.sort(key=lambda x: x["name"].lower())
    return found


def _extract_dict_refs_from_query_frame_action(action_data: Any) -> List[Dict[str, str]]:
    # Dlya sebya: fallback-spisok iz query_user_dict_frame (user_table_frame).
    if not isinstance(action_data, dict):
        return []

    frames = action_data.get("user_table_frame")
    if not isinstance(frames, list):
        return []

    found: List[Dict[str, str]] = []
    seen: set[str] = set()

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        name = str(frame.get("ut_name") or frame.get("ut_name_real") or "").strip()
        uid = str(frame.get("ut_id_uuid") or frame.get("ut_id") or frame.get("id") or "").strip()
        if not name:
            continue
        marker = f"{uid}|{name}".lower()
        if marker in seen:
            continue
        seen.add(marker)
        found.append({"name": name, "uid": uid})

    found.sort(key=lambda x: x["name"].lower())
    return found


def _is_invalid_vector_subscript_error(description: Any) -> bool:
    text = str(description or "").strip().lower()
    return "invalid vector subscript" in text


def _is_alias_not_found_error(description: Any) -> bool:
    text = str(description or "").strip().lower()
    return "alias not found" in text


def _is_dict_not_found_error(description: Any) -> bool:
    text = str(description or "").strip().lower()
    markers = (
        "справочник",
        "не найден",
        "not found",
    )
    return all(marker in text for marker in markers)


def _is_query_v2_incompatible_error(description: Any) -> bool:
    text = str(description or "").strip().lower()
    if not text:
        return False
    markers = (
        "value out of range",
        "dict_last_modified",
        "date_time",
        "РґР°С‚Р° Рё РІСЂРµРјСЏ РїРѕСЃР»РµРґРЅРµРіРѕ РёР·РјРµРЅРµРЅРёСЏ",
    )
    return any(marker in text for marker in markers)


async def _send_select_fields_with_fallback(
    *,
    dict_name: str,
    filters: Optional[List[Dict[str, Any]]] = None,
    order_by: Optional[List[Dict[str, Any]]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    expand_links: bool = False,
    retry_uuid: Optional[str] = None,
    final_action_timeout: Optional[float] = None,
    fast_mode: bool = False,
) -> Dict[str, Any]:
    variants: List[Dict[str, Any]] = []
    template_variants = [
        "select_fields_user_dict_v2",
        "select_fields_user_dict_v1",
        "select_fields_user_dict",
    ]
    for template_alias in template_variants:
        variants.append(
            {
                "template_alias": template_alias,
                "filters": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
                "expand_links": expand_links,
            }
        )

    if not order_by and not fast_mode:
        for template_alias in template_variants:
            variants.append(
                {
                    "template_alias": template_alias,
                    "filters": filters,
                    "order_by": [{"column": "uuid", "direction": DEFAULT_ORDER_DIRECTION}],
                    "limit": limit if limit is not None else 200,
                    "offset": offset if offset is not None else 0,
                    "expand_links": expand_links,
                }
            )

    safe_retry_uuid = str(retry_uuid or "").strip()
    if safe_retry_uuid and not filters:
        for template_alias in template_variants:
            variants.append(
                {
                    "template_alias": template_alias,
                    "filters": [{"column": "uuid", "condition": DEFAULT_FILTER_CONDITION, "value": safe_retry_uuid}],
                    "order_by": [{"column": "uuid", "direction": DEFAULT_ORDER_DIRECTION}],
                    "limit": 1,
                    "offset": 0,
                    "expand_links": expand_links,
                }
            )
            if fast_mode:
                break

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in variants:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)

    last: Optional[Dict[str, Any]] = None
    for idx, cfg in enumerate(deduped):
        xml_body = user_dict_xml.build_select_fields_user_dict_xml(
            dict_name=dict_name,
            filters=cfg.get("filters"),
            order_by=cfg.get("order_by"),
            limit=cfg.get("limit"),
            offset=cfg.get("offset"),
            expand_links=bool(cfg.get("expand_links")),
            template_alias=str(cfg.get("template_alias") or "select_fields_user_dict_v1"),
        )
        resp, final_action = await _send_xml(
            "select_fields_user_dict_v1",
            xml_body,
            accept_action=True,
            capture_final_action=True,
            final_action_timeout=final_action_timeout,
        )
        result = _result(resp)
        _attach_action_payload(result, final_action)
        full = result | {"request_xml": xml_body, "run_id": 0}
        last = full

        if full.get("status") == "ok":
            return full
        if idx < len(deduped) - 1 and (
            _is_invalid_vector_subscript_error(full.get("description"))
            or _is_alias_not_found_error(full.get("description"))
        ):
            continue
        return full

    return last or {"status": "fail", "description": "select_fields failed", "request_xml": "", "run_id": 0}


async def _execute_xml_operation(
    *,
    alias_fallback: str,
    xml_body: str,
    operation: str,
    accept_action: bool = True,
    capture_final_action: bool = True,
    require_completed: bool = False,
    transport_retries: int = 1,
    final_action_timeout: Optional[float] = EXECUTE_XML_FINAL_ACTION_TIMEOUT_SEC,
    wait_non_system_response: bool = True,
) -> Dict[str, Any]:
    # Dlya sebya: odno mesto dlya vypolneniya XML-shaga i sborki normalizovannogo rezultata.
    started = datetime.now(timezone.utc).timestamp()
    attempts = max(1, int(transport_retries) + 1)
    last_exc: Optional[HTTPException] = None
    resp = None
    final_action: Optional[Ai_Documents_pb2.SendActionRequest] = None

    for attempt in range(1, attempts + 1):
        try:
            if capture_final_action:
                resp, final_action = await _send_xml(
                    alias_fallback,
                    xml_body,
                    accept_action=accept_action,
                    capture_final_action=True,
                    final_action_timeout=final_action_timeout,
                    wait_non_system_response=wait_non_system_response,
                )
            else:
                resp = await _send_xml(
                    alias_fallback,
                    xml_body,
                    accept_action=accept_action,
                    capture_final_action=False,
                    final_action_timeout=final_action_timeout,
                    wait_non_system_response=wait_non_system_response,
                )
            break
        except HTTPException as e:
            last_exc = e
            is_transport = e.status_code == 502 and "ISHD" in str(e.detail)
            if not is_transport or attempt >= attempts:
                raise
            logger.warning(
                "Retrying ISHD transport operation=%s attempt=%s/%s detail=%s",
                operation,
                attempt,
                attempts,
                e.detail,
            )
            await asyncio.sleep(min(0.5 * attempt, 1.5))

    if resp is None:
        if last_exc is not None:
            raise last_exc
        raise HTTPException(status_code=502, detail=f"ISHD transport error: operation={operation}")

    result = _result(resp)
    _attach_action_payload(result, final_action)
    if require_completed:
        _require_completed_final_state(result, operation=operation)
    output = result | {"request_xml": xml_body}
    elapsed_ms = (datetime.now(timezone.utc).timestamp() - started) * 1000.0
    perf_monitor.record_operation(name=f"dicts.{operation}", duration_ms=elapsed_ms)
    return output


async def _run_user_dict_autotest(
    payload: AutoTestRunRequest,
    session: AsyncSession,
    *,
    progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    # Dlya sebya: glavnyy orchestration-polotno "odin klik -> polnyy progon -> otchet".
    source_dict_name = payload.source_dict_name.strip()
    if not source_dict_name:
        raise HTTPException(status_code=400, detail="source_dict_name must not be empty")

    run_id = _build_autotest_run_id()
    started_at = _utc_now_iso()
    steps: List[Dict[str, Any]] = []
    temporary_dicts: List[str] = []
    total_steps = _autotest_total_steps(payload)
    completed_steps = 0
    passed_steps = 0
    failed_steps = 0
    skipped_steps = 0

    logger_run_id = await test_run_logger.create_run(session, "autotest_user_dicts")

    source_query_rows: List[Dict[str, Any]] = []
    source_frames: List[Dict[str, Any]] = []
    source_file_columns: List[str] = []
    source_file_row_id: Optional[str] = None
    source_file_column: Optional[str] = None
    source_file_expected_name: Optional[str] = None
    source_file_expected_bytes: Optional[bytes] = None
    run_artifacts: List[Dict[str, Any]] = []
    effective_source_dict_name = source_dict_name
    temp_crud_dict_name = _build_temp_dict_name(payload.test_prefix, source_dict_name, "crud")
    temp_all_types_name = _build_temp_dict_name(payload.test_prefix, source_dict_name, "types")
    temp_crud_created = False
    temp_all_types_created = False
    inserted_row_id: Optional[str] = None
    insert_marker = f"auto_marker_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    updated_marker = insert_marker + "_updated"

    async def emit_progress(event: Dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            await progress_cb(event)
        except Exception as e:
            logger.debug("Autotest progress callback error: %s", e)

    await emit_progress(
        {
            "event": "started",
            "total_steps": total_steps,
            "completed_steps": 0,
            "source_dict_name": source_dict_name,
        }
    )

    async def run_step(step_code: str, title: str, executor):
        # Dlya sebya: kazhdyy shag vypolnyaem odinakovo i pishem v chelovecheskiy log.
        step_started = datetime.now(timezone.utc)
        step_payload: Dict[str, Any] = {}
        step_status = "failed"
        message = ""
        error_source = ""
        scope = "preinstalled" if step_code.startswith("source.") else "temporary"
        step_index = len(steps) + 1
        step_title = _repair_mojibake_text(str(title or ""))
        await emit_progress(
            {
                "event": "step_started",
                "index": step_index,
                "code": step_code,
                "title": step_title,
                "total_steps": total_steps,
            }
        )
        try:
            step_payload = await executor()
            step_status = str(step_payload.get("status", "passed")).strip().lower() or "passed"
            message = _repair_mojibake_text(str(step_payload.get("message", "")).strip())
        except Exception as e:
            step_status = "failed"
            message = _repair_mojibake_text(str(e))
        error_source = _detect_error_source(step_status, message)
        message = _attach_error_source_prefix(message, error_source, step_status)

        duration_ms = int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000)
        step_result = step_payload.get("result")
        raw_result = step_payload.get("raw_result")
        request_xml = step_payload.get("request_xml")

        item: Dict[str, Any] = {
            "code": step_code,
            "scope": scope,
            "title": step_title,
            "status": step_status,
            "duration_ms": duration_ms,
            "message": message,
            "result": step_result,
        }
        if error_source:
            item["error_source"] = error_source
        if payload.verbose_steps and request_xml:
            item["request_xml"] = request_xml
        if payload.verbose_steps and raw_result is not None:
            item["raw_result"] = raw_result
        steps.append(item)

        nonlocal completed_steps, passed_steps, failed_steps, skipped_steps
        completed_steps += 1
        if step_status == "passed":
            passed_steps += 1
        elif step_status == "failed":
            failed_steps += 1
        elif step_status == "skipped":
            skipped_steps += 1
        await emit_progress(
            {
                "event": "step_finished",
                "index": step_index,
                "code": step_code,
                "title": step_title,
                "status": step_status,
                "message": message,
                "error_source": error_source,
                "duration_ms": duration_ms,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "passed": passed_steps,
                "failed": failed_steps,
                "skipped": skipped_steps,
            }
        )

        await test_run_logger.log_step(
            session,
            logger_run_id,
            len(steps),
            request=request_xml if isinstance(request_xml, str) else None,
            response=item,
            status="ok" if step_status == "passed" else ("skip" if step_status == "skipped" else "fail"),
            message=f"{step_code}: {message}".strip(),
        )

    async def _execute_autotest_xml(
        *,
        alias_fallback: str,
        xml_body: str,
        operation: str,
        require_completed: bool = False,
    ) -> Dict[str, Any]:
        # Dlya sebya: autotest dolzhen rabotat' bystree, poetomu umenshaem wait final-action.
        return await _execute_xml_operation(
            alias_fallback=alias_fallback,
            xml_body=xml_body,
            operation=operation,
            require_completed=require_completed,
            transport_retries=0,
            final_action_timeout=AUTOTEST_STEP_FINAL_ACTION_TIMEOUT_SEC,
            wait_non_system_response=False,
        )

    async def source_query_frame_step() -> Dict[str, Any]:
        nonlocal source_frames, source_file_columns, effective_source_dict_name
        xml_body = user_dict_xml.build_query_user_dict_frame_xml(source_dict_name)
        full = await _execute_autotest_xml(
            alias_fallback="query_user_dict_frame",
            xml_body=xml_body,
            operation="query_frame",
            require_completed=True,
        )
        compact = _compact_query_frame_response(
            dict_name=source_dict_name,
            result=full,
            run_id=0,
        )
        source_frames = compact.get("frames", []) if isinstance(compact.get("frames"), list) else []
        source_file_columns = _extract_file_columns_from_frames(source_frames)
        resolved_name = _resolve_effective_dict_name_from_query_frame(
            action_data=full.get("action_data"),
            requested_name=source_dict_name,
        )
        if resolved_name:
            effective_source_dict_name = resolved_name
        elif source_frames:
            # fallback na compact-frame imena, esli action_data ne sobralas.
            requested_lower = source_dict_name.strip().lower()
            best_name = ""
            for frame in source_frames:
                if not isinstance(frame, dict):
                    continue
                frame_name = str(frame.get("name_real") or frame.get("name") or "").strip()
                if not frame_name:
                    continue
                if frame_name.lower() == requested_lower:
                    best_name = frame_name
                    break
                if requested_lower.endswith(frame_name.lower()) or frame_name.lower().endswith(requested_lower):
                    best_name = frame_name
            if best_name:
                effective_source_dict_name = best_name
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "query-frame failed",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": f"Структура получена: frames={compact.get('frames_count', 0)}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def source_metainfo_step() -> Dict[str, Any]:
        dict_name_for_step = effective_source_dict_name
        candidates: List[str] = []
        for name in (
            dict_name_for_step,
            str(dict_name_for_step or "").split(".")[-1].strip(),
            source_dict_name,
            str(source_dict_name or "").split(".")[-1].strip(),
        ):
            nm = str(name or "").strip()
            if nm and nm not in candidates:
                candidates.append(nm)
        for frame in source_frames:
            if not isinstance(frame, dict):
                continue
            for key in ("name_real", "name"):
                nm = str(frame.get(key) or "").strip()
                if nm and nm not in candidates:
                    candidates.append(nm)
            frame_id = str(frame.get("id") or "").strip()
            if frame_id and frame_id not in candidates:
                candidates.append(frame_id)

        full: Dict[str, Any] = {}
        xml_body = ""
        for candidate in candidates:
            xml_candidate = user_dict_xml.build_query_user_dict_metainfo_xml(candidate)
            try:
                full_candidate = await _execute_autotest_xml(
                    alias_fallback="query_user_dict_metainfo",
                    xml_body=xml_candidate,
                    operation="metainfo",
                    require_completed=True,
                )
            except HTTPException as exc:
                full_candidate = {
                    "status": "fail",
                    "description": str(exc.detail or ""),
                    "request_xml": xml_candidate,
                    "action_data": {},
                }
            if full_candidate.get("status") == "ok":
                full = full_candidate
                xml_body = xml_candidate
                dict_name_for_step = candidate
                break
            if not full:
                full = full_candidate
                xml_body = xml_candidate
        compact = _compact_metainfo_response(
            dict_name=dict_name_for_step,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            # Fallback: v nekotoryh sborkah metainfo po imeni/uid nedostupen,
            # no query_frame uzhe podtverdil nalichie spravochnika i ego struktury.
            if source_frames:
                frame_hit: Optional[Dict[str, Any]] = None
                requested_lower = str(dict_name_for_step or source_dict_name).strip().lower()
                for frame in source_frames:
                    if not isinstance(frame, dict):
                        continue
                    fname = str(frame.get("name_real") or frame.get("name") or "").strip()
                    if not fname:
                        continue
                    if (
                        fname.lower() == requested_lower
                        or requested_lower.endswith(fname.lower())
                        or fname.lower().endswith(requested_lower)
                    ):
                        frame_hit = frame
                        break
                if frame_hit is None:
                    frame_hit = source_frames[0] if isinstance(source_frames[0], dict) else None
                if isinstance(frame_hit, dict):
                    fallback_compact = {
                        "status": "ok",
                        "report_code_name": "DONE",
                        "description": "",
                        "operation": "metainfo",
                        "dict_name": str(frame_hit.get("name_real") or frame_hit.get("name") or dict_name_for_step),
                        "dict_id": frame_hit.get("id"),
                        "dict_name_value": str(frame_hit.get("name_real") or frame_hit.get("name") or dict_name_for_step),
                        "dict_size": None,
                        "dict_last_modified": None,
                        "run_id": 0,
                        "fallback_source": "query_frame",
                    }
                    return {
                        "status": "passed",
                        "message": "Метаинформация подтверждена через query_frame (fallback для текущей сборки).",
                        "result": fallback_compact,
                        "raw_result": full,
                        "request_xml": xml_body,
                    }
            return {
                "status": "failed",
                "message": full.get("description") or "metainfo failed",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "Метаинформация получена",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def source_query_step() -> Dict[str, Any]:
        nonlocal source_query_rows, source_file_row_id, source_file_columns
        xml_body = user_dict_xml.build_query_user_dict_xml(effective_source_dict_name, prefer_v2=True)
        try:
            full = await _execute_autotest_xml(
                alias_fallback="query_user_dict",
                xml_body=xml_body,
                operation="query",
                require_completed=True,
            )
        except Exception as exc:
            if _is_query_v2_incompatible_error(str(exc)):
                xml_body = user_dict_xml.build_query_user_dict_xml(effective_source_dict_name, prefer_v2=False)
                full = await _execute_autotest_xml(
                    alias_fallback="query_user_dict",
                    xml_body=xml_body,
                    operation="query",
                    require_completed=True,
                )
            else:
                raise
        if full["status"] != "ok" and _is_query_v2_incompatible_error(full.get("description")):
            xml_body = user_dict_xml.build_query_user_dict_xml(effective_source_dict_name, prefer_v2=False)
            full = await _execute_autotest_xml(
                alias_fallback="query_user_dict",
                xml_body=xml_body,
                operation="query",
                require_completed=True,
            )
        compact = _compact_query_response(
            dict_name=effective_source_dict_name,
            result=full,
            run_id=0,
            operation="query",
        )
        source_query_rows = compact.get("rows", []) if isinstance(compact.get("rows"), list) else []
        source_file_row_id = None
        preferred_file_column = _pick_best_file_column(source_file_columns, source_query_rows)
        if preferred_file_column:
            for row in source_query_rows:
                if not isinstance(row, dict):
                    continue
                raw_uuid = str(row.get("uuid") or "").strip()
                if not raw_uuid:
                    continue
                if _has_visible_file_value(row.get(preferred_file_column)):
                    source_file_row_id = raw_uuid
                    break
        for row in source_query_rows:
            if not isinstance(row, dict):
                continue
            raw_uuid = str(row.get("uuid") or "").strip()
            if not raw_uuid:
                continue
            if source_file_row_id is None:
                source_file_row_id = raw_uuid
        if not source_file_columns:
            source_file_columns = _extract_file_columns_from_rows(source_query_rows)
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "query failed",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": f"Содержимое получено, строк: {compact.get('found_count', 0)}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def source_select_fields_step() -> Dict[str, Any]:
        retry_uuid = str(source_file_row_id or "").strip()
        if not retry_uuid:
            for row in source_query_rows:
                if not isinstance(row, dict):
                    continue
                raw_uuid = str(row.get("uuid") or "").strip()
                if raw_uuid:
                    retry_uuid = raw_uuid
                    break

        full = await _send_select_fields_with_fallback(
            dict_name=effective_source_dict_name,
            filters=None,
            order_by=None,
            limit=20,
            offset=0,
            expand_links=False,
            retry_uuid=retry_uuid or None,
            final_action_timeout=AUTOTEST_STEP_FINAL_ACTION_TIMEOUT_SEC,
            fast_mode=True,
        )
        xml_body = str(full.get("request_xml") or "")
        compact = _compact_select_fields_response(
            dict_name=effective_source_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            if source_query_rows and (
                _is_invalid_vector_subscript_error(full.get("description"))
                or _is_alias_not_found_error(full.get("description"))
                or _is_dict_not_found_error(full.get("description"))
            ):
                fallback_compact = {
                    "status": "ok",
                    "report_code_name": "DONE",
                    "description": "",
                    "dict_name": effective_source_dict_name,
                    "found_count": len(source_query_rows),
                    "rows": source_query_rows,
                    "row_ids": [
                        str(row.get("uuid") or "").strip()
                        for row in source_query_rows
                        if isinstance(row, dict) and str(row.get("uuid") or "").strip()
                    ],
                    "run_id": 0,
                    "fallback_source": "query",
                }
                return {
                    "status": "passed",
                    "message": "Select-fields подтвержден через query (fallback для текущей сборки).",
                    "result": fallback_compact,
                    "raw_result": full,
                    "request_xml": xml_body,
                }
            if _is_invalid_vector_subscript_error(full.get("description")):
                return {
                    "status": "failed",
                    "message": full.get("description") or "select-fields failed: invalid vector subscript",
                    "result": compact,
                    "raw_result": full,
                    "request_xml": xml_body,
                }
            return {
                "status": "failed",
                "message": full.get("description") or "select-fields failed",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": f"Select-fields вернул строк: {compact.get('found_count', 0)}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def source_search_step() -> Dict[str, Any]:
        chosen_filter: Optional[Dict[str, Any]] = None
        for row in source_query_rows:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                if key == "uuid":
                    continue
                if isinstance(value, str) and value.strip():
                    chosen_filter = {
                        "column": key,
                        "condition": DEFAULT_FILTER_CONDITION,
                        "value": value.strip(),
                    }
                    break
            if chosen_filter:
                break

        if not chosen_filter:
            return {
                "status": "skipped",
                "message": "Поиск по предустановленному справочнику пропущен: нет подходящего текстового поля в query.",
                "result": {"dict_name": source_dict_name},
            }

        xml_body = user_dict_xml.build_query_single_user_dict_xml(effective_source_dict_name, [chosen_filter])
        full = await _execute_autotest_xml(
            alias_fallback="query_single_user_dict",
            xml_body=xml_body,
            operation="search",
            require_completed=True,
        )
        compact = _compact_search_response(
            dict_name=effective_source_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "search failed",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        if int(compact.get("found_count", 0) or 0) <= 0:
            return {
                "status": "failed",
                "message": "Поиск выполнился, но не вернул строк.",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": f"Поиск вернул строк: {compact.get('found_count', 0)}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def source_file_upload_step() -> Dict[str, Any]:
        nonlocal source_file_column, source_file_expected_name, source_file_expected_bytes
        source_file_column = None
        source_file_expected_name = None
        source_file_expected_bytes = None

        selected_file_column = _pick_best_file_column(source_file_columns, source_query_rows)
        if selected_file_column:
            source_file_column = selected_file_column
        if not source_file_columns:
            return {
                "status": "skipped",
                "message": "РЁР°Рі РїСЂРѕРїСѓС‰РµРЅ: РІ СЃС‚СЂСѓРєС‚СѓСЂРµ СЃРїСЂР°РІРѕС‡РЅРёРєР° РЅРµС‚ РєРѕР»РѕРЅРѕРє file/input_file.",
                "result": {"dict_name": source_dict_name},
            }
        if not source_file_row_id:
            return {
                "status": "skipped",
                "message": "РЁР°Рі РїСЂРѕРїСѓС‰РµРЅ: РІ СЃРїСЂР°РІРѕС‡РЅРёРєРµ РЅРµС‚ СЃС‚СЂРѕРєРё СЃ uuid РґР»СЏ С‚РµСЃС‚Р° С„Р°Р№Р»Р°.",
                "result": {"dict_name": source_dict_name},
            }
        if not source_file_column:
            return {
                "status": "skipped",
                "message": "РЁР°Рі РїСЂРѕРїСѓС‰РµРЅ: РЅРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РєРѕР»РѕРЅРєСѓ СЃ С„Р°Р№Р»РѕРј РґР»СЏ upload/download.",
                "result": {"dict_name": source_dict_name},
            }
        return {
            "status": "skipped",
            "message": (
                f"РЁР°Рі РїСЂРѕРїСѓС‰РµРЅ: upload РІ РїСЂРµРґСѓСЃС‚Р°РЅРѕРІР»РµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РѕС‚РєР»СЋС‡РµРЅ РІ Р±РµР·РѕРїР°СЃРЅРѕРј СЂРµР¶РёРјРµ. "
                f"Р‘СѓРґРµС‚ РїСЂРѕРІРµСЂРµРЅРѕ С‚РѕР»СЊРєРѕ СЃРєР°С‡РёРІР°РЅРёРµ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРіРѕ С„Р°Р№Р»Р° РёР· РєРѕР»РѕРЅРєРё '{source_file_column}'."
            ),
            "result": {"dict_name": effective_source_dict_name, "column": source_file_column},
        }
    async def source_file_download_step() -> Dict[str, Any]:
        nonlocal source_file_column, source_file_row_id
        # Autodetect first real file in any file-like column to avoid manual row/column dependency.
        candidate_cols: List[str] = []
        if source_file_column:
            candidate_cols.append(source_file_column)
        for col in source_file_columns:
            if col and col not in candidate_cols:
                candidate_cols.append(col)
        if not candidate_cols and source_query_rows:
            for col in _extract_file_columns_from_rows(source_query_rows):
                if col and col not in candidate_cols:
                    candidate_cols.append(col)

        if source_query_rows:
            fallback_uuid: Optional[str] = None
            for row in source_query_rows:
                if not isinstance(row, dict):
                    continue
                raw_uuid = str(row.get("uuid") or "").strip()
                if not raw_uuid:
                    continue
                if fallback_uuid is None:
                    fallback_uuid = raw_uuid
                for col in candidate_cols:
                    if _has_visible_file_value(row.get(col)):
                        source_file_row_id = raw_uuid
                        source_file_column = col
                        break
                if source_file_row_id and source_file_column:
                    break
            if source_file_row_id is None and fallback_uuid:
                source_file_row_id = fallback_uuid

        if not source_file_column:
            source_file_column = _pick_best_file_column(candidate_cols, source_query_rows)

        if not source_file_column or not source_file_row_id:
            return {
                "status": "skipped",
                "message": "Шаг пропущен: не удалось определить row_id/колонку для скачивания файла.",
                "result": {"dict_name": source_dict_name},
            }
        xml_body = user_dict_xml.build_query_single_user_dict_xml(
            effective_source_dict_name,
            [{"column": "uuid", "value": source_file_row_id}],
        )
        full = await _execute_autotest_xml(
            alias_fallback="query_single_user_dict",
            xml_body=xml_body,
            operation="source_file_download_query",
            require_completed=True,
        )
        compact = _compact_search_response(
            dict_name=effective_source_dict_name,
            result=full,
            run_id=0,
        )
        rows = compact.get("rows", [])
        if not isinstance(rows, list):
            rows = []
        if not rows:
            return {
                "status": "failed",
                "message": "Не удалось получить строку справочника для проверки скачивания файла.",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }

        ordered_rows: List[Dict[str, Any]] = []
        preferred_row: Optional[Dict[str, Any]] = None
        for row in rows:
            if isinstance(row, dict) and str(row.get("uuid", "")).strip() == source_file_row_id:
                preferred_row = row
                break
        if isinstance(preferred_row, dict):
            ordered_rows.append(preferred_row)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if preferred_row is row:
                continue
            ordered_rows.append(row)
        if not ordered_rows:
            return {
                "status": "failed",
                "message": "Не удалось выбрать строку для проверки скачивания файла.",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }

        ordered_cols: List[str] = []
        if source_file_column:
            ordered_cols.append(source_file_column)
        for col in candidate_cols:
            if col and col not in ordered_cols:
                ordered_cols.append(col)
        for row in ordered_rows:
            for key in row.keys():
                key_name = str(key or "").strip()
                if not key_name or key_name.lower() == "uuid":
                    continue
                if key_name not in ordered_cols:
                    ordered_cols.append(key_name)

        file_blob: Optional[Dict[str, Any]] = None
        last_detail: Optional[str] = None
        for row in ordered_rows:
            if file_blob is not None:
                break
            row_uuid = str(row.get("uuid") or "").strip()
            for col in ordered_cols:
                resolved_col = _resolve_column_name_case_insensitive(col, list(row.keys())) or col
                if resolved_col not in row:
                    continue
                value = row.get(resolved_col)
                if not _has_visible_file_value(value):
                    continue
                file_ids = _extract_file_id_candidates_from_value(value)
                if not file_ids:
                    continue
                # Быстрый локальный путь: во многих сборках file-значение уже содержит
                # path/base64, и ждать documentfilesget не нужно.
                with suppress(HTTPException):
                    file_blob = _extract_file_blob_from_value(value, file_index=0)
                if file_blob is not None:
                    source_file_row_id = row_uuid or source_file_row_id
                    source_file_column = resolved_col
                    break
                try:
                    # Dlya sebya: v autoteste ogranichivaem dolgij wait na documentfilesget.
                    file_blob = await _download_file_blob_via_documentfilesget(
                        file_ids=file_ids,
                        file_index=0,
                        max_id_variants=2,
                        per_request_timeout_sec=3.0,
                    )
                except HTTPException as exc:
                    last_detail = str(exc.detail)
                    if file_blob is None:
                        with suppress(HTTPException):
                            file_blob = await _download_file_blob_from_paragraph_db_by_ai_id(
                                row_value=value,
                                dict_name=effective_source_dict_name,
                                column_name=resolved_col,
                                file_index=0,
                            )
                    if file_blob is None and row_uuid:
                        with suppress(HTTPException):
                            file_blob = await _download_file_blob_from_paragraph_db(
                                dict_name=effective_source_dict_name,
                                row_id=row_uuid,
                                column_name=resolved_col,
                                file_index=0,
                            )
                if file_blob is not None:
                    source_file_row_id = row_uuid or source_file_row_id
                    source_file_column = resolved_col
                    break
        if file_blob is None:
            return {
                "status": "failed",
                "message": (
                    f"Не удалось скачать файл из поля '{source_file_column}' через documentfilesget"
                    + (f": {last_detail}" if last_detail else "")
                ),
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }

        downloaded_bytes = bytes(file_blob.get("bytes") or b"")
        expected_bytes = bytes(source_file_expected_bytes or b"")
        if not downloaded_bytes:
            return {
                "status": "failed",
                "message": "Файл получен, но payload пустой.",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        if expected_bytes and downloaded_bytes != expected_bytes:
            return {
                "status": "failed",
                "message": "Содержимое скачанного файла не совпало с ожидаемым.",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }

        downloaded_name = (
            str(file_blob.get("filename") or "").strip()
            or str(source_file_expected_name or "").strip()
            or f"{effective_source_dict_name}_{source_file_column}_{run_id}.bin"
        )
        artifact_meta = autotest_reports.save_artifact(
            run_id=run_id,
            data=downloaded_bytes,
            filename=downloaded_name,
            content_type=_guess_media_type_from_filename(downloaded_name),
            kind="dict_file_download",
            step_code="source.file.download",
        )
        run_artifacts.append(artifact_meta)

        return {
            "status": "passed",
            "message": f"Файл успешно скачан из справочника: {downloaded_name}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def all_types_create_step() -> Dict[str, Any]:
        nonlocal temp_all_types_created
        columns = _make_all_types_columns(source_dict_name)
        xml_body = user_dict_xml.build_create_user_dict_xml(
            dict_name=temp_all_types_name,
            columns=columns,
            preset=None,
        )
        full = await _execute_autotest_xml(
            alias_fallback="create_user_dict",
            xml_body=xml_body,
            operation="create_all_types",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="create_all_types",
            dict_name=temp_all_types_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РЎРѕР·РґР°РЅРёРµ all-types СЃРїСЂР°РІРѕС‡РЅРёРєР° РЅРµ СѓРґР°Р»РѕСЃСЊ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        temp_all_types_created = True
        temporary_dicts.append(temp_all_types_name)
        return {
            "status": "passed",
            "message": "All-types smoke: СЃРїСЂР°РІРѕС‡РЅРёРє СЃРѕР·РґР°РЅ",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def all_types_delete_step() -> Dict[str, Any]:
        if not temp_all_types_created:
            return {
                "status": "skipped",
                "message": "РЈРґР°Р»РµРЅРёРµ all-types РїСЂРѕРїСѓС‰РµРЅРѕ: create-С€Р°Рі РЅРµ РїСЂРѕС€РµР».",
                "result": {"dict_name": temp_all_types_name},
            }
        xml_body = user_dict_xml.build_remove_user_dict_xml(temp_all_types_name)
        full = await _execute_autotest_xml(
            alias_fallback="remove_user_dict",
            xml_body=xml_body,
            operation="remove_all_types",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="remove_all_types",
            dict_name=temp_all_types_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РЈРґР°Р»РµРЅРёРµ all-types СЃРїСЂР°РІРѕС‡РЅРёРєР° РЅРµ СѓРґР°Р»РѕСЃСЊ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "All-types smoke: СЃРїСЂР°РІРѕС‡РЅРёРє СѓРґР°Р»РµРЅ",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_create_step() -> Dict[str, Any]:
        nonlocal temp_crud_created
        xml_body = user_dict_xml.build_create_user_dict_xml(
            dict_name=temp_crud_dict_name,
            preset="base_card",
        )
        full = await _execute_autotest_xml(
            alias_fallback="create_user_dict",
            xml_body=xml_body,
            operation="create",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="create",
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РЎРѕР·РґР°РЅРёРµ РІСЂРµРјРµРЅРЅРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР° РЅРµ СѓРґР°Р»РѕСЃСЊ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        temp_crud_created = True
        temporary_dicts.append(temp_crud_dict_name)
        return {
            "status": "passed",
            "message": "Р’СЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РґР»СЏ CRUD СЃРѕР·РґР°РЅ",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_insert_step() -> Dict[str, Any]:
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "Insert РїСЂРѕРїСѓС‰РµРЅ: РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РЅРµ СЃРѕР·РґР°РЅ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        row = {
            "name": "auto_row_" + insert_marker,
            "description": insert_marker,
            "is_active": True,
        }
        xml_body = user_dict_xml.build_insert_user_dict_xml(temp_crud_dict_name, [row])
        full = await _execute_autotest_xml(
            alias_fallback="insert_user_dict",
            xml_body=xml_body,
            operation="insert",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="insert",
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "Insert не выполнен",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "Insert выполнен",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_search_inserted_step() -> Dict[str, Any]:
        nonlocal inserted_row_id
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "Search РїСЂРѕРїСѓС‰РµРЅ: РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РЅРµ СЃРѕР·РґР°РЅ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        xml_body = user_dict_xml.build_query_single_user_dict_xml(
            temp_crud_dict_name,
            [{"column": "description", "condition": DEFAULT_FILTER_CONDITION, "value": insert_marker}],
        )
        full = await _execute_autotest_xml(
            alias_fallback="query_single_user_dict",
            xml_body=xml_body,
            operation="search_inserted",
            require_completed=True,
        )
        compact = _compact_search_response(
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
        )
        if compact.get("row_ids"):
            inserted_row_id = compact["row_ids"][0]

        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "Search РїРѕСЃР»Рµ insert РЅРµ РІС‹РїРѕР»РЅРµРЅ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        if int(compact.get("found_count", 0) or 0) <= 0:
            return {
                "status": "failed",
                "message": "Search РїРѕСЃР»Рµ insert РЅРµ РЅР°С€РµР» РґРѕР±Р°РІР»РµРЅРЅСѓСЋ СЃС‚СЂРѕРєСѓ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": f"Р”РѕР±Р°РІР»РµРЅРЅР°СЏ СЃС‚СЂРѕРєР° РЅР°Р№РґРµРЅР°, row_id={inserted_row_id or '-'}",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_update_step() -> Dict[str, Any]:
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "Update РїСЂРѕРїСѓС‰РµРЅ: РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РЅРµ СЃРѕР·РґР°РЅ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        if not inserted_row_id:
            return {
                "status": "skipped",
                "message": "Update РїСЂРѕРїСѓС‰РµРЅ: РЅРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ row_id РїРѕСЃР»Рµ insert/search.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        xml_body = user_dict_xml.build_update_user_dict_xml(
            temp_crud_dict_name,
            inserted_row_id,
            {"description": updated_marker},
        )
        full = await _execute_autotest_xml(
            alias_fallback="update_user_dict",
            xml_body=xml_body,
            operation="update",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="update",
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
            extra={"row_id": inserted_row_id},
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "Update не выполнен",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "Update выполнен",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_remove_row_step() -> Dict[str, Any]:
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "remove-rows РїСЂРѕРїСѓС‰РµРЅ: РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РЅРµ СЃРѕР·РґР°РЅ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        if not inserted_row_id:
            return {
                "status": "skipped",
                "message": "remove-rows РїСЂРѕРїСѓС‰РµРЅ: РЅРµС‚ row_id РґР»СЏ СѓРґР°Р»РµРЅРёСЏ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        xml_body = user_dict_xml.build_remove_from_user_dict_xml(
            dict_name=temp_crud_dict_name,
            row_ids=[inserted_row_id],
            filters=None,
        )
        full = await _execute_autotest_xml(
            alias_fallback="remove_from_user_dict",
            xml_body=xml_body,
            operation="remove_rows",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="remove_rows",
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
            extra={"row_id": inserted_row_id},
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РЈРґР°Р»РµРЅРёРµ СЃС‚СЂРѕРєРё РЅРµ РІС‹РїРѕР»РЅРµРЅРѕ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "РЈРґР°Р»РµРЅРёРµ СЃС‚СЂРѕРєРё РІС‹РїРѕР»РЅРµРЅРѕ",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_verify_removed_step() -> Dict[str, Any]:
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "РџСЂРѕРІРµСЂРєР° СѓРґР°Р»РµРЅРёСЏ РїСЂРѕРїСѓС‰РµРЅР°: РІСЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє РЅРµ СЃРѕР·РґР°РЅ.",
                "result": {"dict_name": temp_crud_dict_name},
            }
        xml_body = user_dict_xml.build_query_single_user_dict_xml(
            temp_crud_dict_name,
            [{"column": "description", "condition": DEFAULT_FILTER_CONDITION, "value": updated_marker}],
        )
        full = await _execute_autotest_xml(
            alias_fallback="query_single_user_dict",
            xml_body=xml_body,
            operation="verify_removed",
            require_completed=True,
        )
        compact = _compact_search_response(
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РџСЂРѕРІРµСЂРєР° СѓРґР°Р»РµРЅРёСЏ (search) РЅРµ РІС‹РїРѕР»РЅРµРЅР°",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        if int(compact.get("found_count", 0) or 0) != 0:
            return {
                "status": "failed",
                "message": "РџРѕСЃР»Рµ СѓРґР°Р»РµРЅРёСЏ СЃС‚СЂРѕРєР° РІСЃРµ РµС‰Рµ РЅР°С…РѕРґРёС‚СЃСЏ РІ СЃРїСЂР°РІРѕС‡РЅРёРєРµ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "РџСЂРѕРІРµСЂРєР° СѓРґР°Р»РµРЅРёСЏ СѓСЃРїРµС€РЅР°: СЃС‚СЂРѕРєР° РЅРµ РЅР°Р№РґРµРЅР°",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    async def temp_remove_dict_step() -> Dict[str, Any]:
        if not temp_crud_created:
            return {
                "status": "skipped",
                "message": "РЈРґР°Р»РµРЅРёРµ РІСЂРµРјРµРЅРЅРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР° РїСЂРѕРїСѓС‰РµРЅРѕ: create-С€Р°Рі РЅРµ РїСЂРѕС€РµР».",
                "result": {"dict_name": temp_crud_dict_name},
            }
        xml_body = user_dict_xml.build_remove_user_dict_xml(temp_crud_dict_name)
        full = await _execute_autotest_xml(
            alias_fallback="remove_user_dict",
            xml_body=xml_body,
            operation="remove_dict",
            require_completed=True,
        )
        compact = _compact_status_response(
            operation="remove_dict",
            dict_name=temp_crud_dict_name,
            result=full,
            run_id=0,
        )
        if full["status"] != "ok":
            return {
                "status": "failed",
                "message": full.get("description") or "РЈРґР°Р»РµРЅРёРµ РІСЂРµРјРµРЅРЅРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР° РЅРµ РІС‹РїРѕР»РЅРµРЅРѕ",
                "result": compact,
                "raw_result": full,
                "request_xml": xml_body,
            }
        return {
            "status": "passed",
            "message": "Р’СЂРµРјРµРЅРЅС‹Р№ СЃРїСЂР°РІРѕС‡РЅРёРє СѓРґР°Р»РµРЅ",
            "result": compact,
            "raw_result": full,
            "request_xml": xml_body,
        }

    await run_step("source.query_frame", "Предустановленный: структура", source_query_frame_step)
    await run_step("source.metainfo", "Предустановленный: метаинформация", source_metainfo_step)
    await run_step("source.query", "Предустановленный: полный запрос", source_query_step)
    await run_step("source.select_fields", "Предустановленный: выбор полей", source_select_fields_step)
    await run_step("source.search", "Предустановленный: поиск", source_search_step)

    if payload.include_all_types_smoke:
        await run_step("temp.types.create", "Smoke all-types: create", all_types_create_step)
        await run_step("temp.types.remove", "Smoke all-types: remove", all_types_delete_step)

    if payload.include_create_delete:
        await run_step("temp.crud.create", "Временный CRUD: create", temp_create_step)
        await run_step("temp.crud.insert", "Временный CRUD: insert", temp_insert_step)
        await run_step("temp.crud.search", "Временный CRUD: search inserted", temp_search_inserted_step)
        await run_step("temp.crud.update", "Временный CRUD: update", temp_update_step)
        await run_step("temp.crud.remove_rows", "Временный CRUD: remove rows", temp_remove_row_step)
        await run_step("temp.crud.verify_removed", "Временный CRUD: verify removed", temp_verify_removed_step)
        await run_step("temp.crud.remove_dict", "Временный CRUD: remove dict", temp_remove_dict_step)

    await run_step("source.file.download", "Предустановленный: скачивание файла", source_file_download_step)

    passed = sum(1 for s in steps if s.get("status") == "passed")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    skipped = sum(1 for s in steps if s.get("status") == "skipped")
    final_status = "failed" if failed else "passed"
    preinstalled_steps = [s for s in steps if str(s.get("scope")) == "preinstalled"]
    temporary_steps = [s for s in steps if str(s.get("scope")) == "temporary"]

    def _scope_summary(scope_steps: List[Dict[str, Any]]) -> Dict[str, int]:
        return {
            "total": len(scope_steps),
            "passed": sum(1 for s in scope_steps if s.get("status") == "passed"),
            "failed": sum(1 for s in scope_steps if s.get("status") == "failed"),
            "skipped": sum(1 for s in scope_steps if s.get("status") == "skipped"),
        }

    report: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "status": final_status,
        "mode": "user-dicts-only",
        "target_id": _current_target_id(),
        "target_name": _current_target_name(),
        "source_dict_name": source_dict_name,
        "temporary_dicts": temporary_dicts,
        "summary": {
            "total": len(steps),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "preinstalled": _scope_summary(preinstalled_steps),
            "temporary": _scope_summary(temporary_steps),
        },
        "artifacts": run_artifacts,
        "steps": steps,
    }
    report["ui_summary"] = _build_ui_autotest_summary(report)
    await emit_progress(
        {
            "event": "finished",
            "status": final_status,
            "message": "Autotest finished",
            "summary": report.get("summary", {}),
        }
    )

    autotest_reports.save_report(report)
    await test_run_logger.finish_run(session, logger_run_id, "failed" if failed else "success")
    await session.commit()
    return report


def _build_ui_autotest_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    # Dlya sebya: korotkiy chelovecheskiy blok dlya UI/otcheta bez CUDATY JSON.
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    pre = summary.get("preinstalled") if isinstance(summary.get("preinstalled"), dict) else {}
    tmp = summary.get("temporary") if isinstance(summary.get("temporary"), dict) else {}
    steps = report.get("steps") if isinstance(report.get("steps"), list) else []

    failed_steps: List[Dict[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("status", "")).lower() != "failed":
            continue
        failed_steps.append(
            {
                "code": str(step.get("code") or ""),
                "title": str(step.get("title") or ""),
                "message": str(step.get("message") or ""),
            }
        )

    headline = (
        f"Статус: {report.get('status', '-')}. "
        f"Шагов: {summary.get('total', 0)}, "
        f"успешно: {summary.get('passed', 0)}, "
        f"ошибок: {summary.get('failed', 0)}, "
        f"пропущено: {summary.get('skipped', 0)}."
    )
    pre_text = (
        f"Предустановленный справочник: шагов {pre.get('total', 0)}, "
        f"успешно {pre.get('passed', 0)}, ошибок {pre.get('failed', 0)}, пропущено {pre.get('skipped', 0)}."
    )
    tmp_text = (
        f"Временный CRUD: шагов {tmp.get('total', 0)}, "
        f"успешно {tmp.get('passed', 0)}, ошибок {tmp.get('failed', 0)}, пропущено {tmp.get('skipped', 0)}."
    )

    return {
        "headline": headline,
        "preinstalled": pre_text,
        "temporary": tmp_text,
        "failed_steps": failed_steps,
    }


@router.get(
    "/column-types",
    summary="РўРёРїС‹ РїРѕР»РµР№ СЃРїСЂР°РІРѕС‡РЅРёРєР°",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РїРѕРґРґРµСЂР¶РёРІР°РµРјС‹С… С‚РёРїРѕРІ РєРѕР»РѕРЅРѕРє Рё РїСЂРµСЃРµС‚С‹ РґР»СЏ СЃРѕР·РґР°РЅРёСЏ СЃРїСЂР°РІРѕС‡РЅРёРєР°.",
)
async def column_types() -> Dict[str, Any]:
    # Dlya sebya: endpoint "column_types" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    return {
        "default_type": "text",
        "types": user_dict_xml.get_column_type_help(),
        "presets": user_dict_xml.get_create_presets_help(),
        "example": {
            "name": "test_dictionary",
            "columns": [
                {"name": "name", "type": "text", "required": True},
                {"name": "created_at", "type": "datetime", "required": False},
            ],
        },
    }


@router.get(
    "/help",
    summary="РџР°РјСЏС‚РєР° РїРѕ user-dicts",
    description="РљРѕСЂРѕС‚РєР°СЏ РїРѕРґСЃРєР°Р·РєР° РїРѕ РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚Рё РІС‹Р·РѕРІРѕРІ Рё РїСЂРёРјРµСЂС‹ payload.",
)
async def user_dicts_help() -> Dict[str, Any]:
    # Dlya sebya: endpoint "user_dicts_help" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    return {
        "workflow": [
            "1) create -> 2) insert -> 3) search/query/select-fields -> 4) update/remove-rows -> 5) remove",
            "update requires row_id (take it from search/select-fields response).",
            "for quick start use preset in /dicts/create",
        ],
        "examples": {
            "create": {
                "name": "test_auto",
                "preset": "base_card",
            },
            "insert": {
                "name": "test_auto",
                "rows": [{"name": "Ivan", "description": "test", "is_active": True}],
            },
            "insert_file": {
                "name": "test_auto",
                "rows": [
                    {
                        "name": "РЎ Р·Р°РїРёСЃСЊСЋ С„Р°Р№Р»Р°",
                        "file_column": {
                            "filename": "example.txt",
                            "data_base64": "SGVsbG8h",
                        },
                    }
                ],
            },
            "search": {
                "name": "test_auto",
                "filters": [{"column": "name", "condition": DEFAULT_FILTER_CONDITION, "value": "Ivan"}],
            },
            "update": {
                "name": "test_auto",
                "row_id": "<uuid>",
                "values": {"description": "updated"},
            },
            "remove_rows": {
                "name": "test_auto",
                "filters": [{"column": "name", "condition": DEFAULT_FILTER_CONDITION, "value": "Ivan"}],
            },
            "download_file": {
                "name": "test_auto",
                "row_id": "{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}",
                "column": "file_column",
                "file_index": 0,
            },
        },
    }


@router.post(
    "/create",
    summary="РЎРѕР·РґР°С‚СЊ СЃРїСЂР°РІРѕС‡РЅРёРє",
    description="РЎРѕР·РґР°РµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёР№ СЃРїСЂР°РІРѕС‡РЅРёРє РІ РџР°СЂР°РіСЂР°С„Рµ С‡РµСЂРµР· РРЁР”.",
)
async def create_dict(
    payload: CreateDictRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "create_dict" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    columns = [c.model_dump(exclude_none=True) for c in payload.columns] if payload.columns else None
    try:
        xml_body = user_dict_xml.build_create_user_dict_xml(
            dict_name=payload.name,
            columns=columns,
            preset=payload.preset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resp, final_action = await _send_xml(
        "create_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    _require_completed_final_state(result, operation="create")
    run_id = await _log_single_run(
        session,
        run_name="create_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_status_response(
        operation="create",
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/remove",
    summary="РЈРґР°Р»РёС‚СЊ СЃРїСЂР°РІРѕС‡РЅРёРє",
    description="РЈРґР°Р»СЏРµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёР№ СЃРїСЂР°РІРѕС‡РЅРёРє РїРѕ РёРјРµРЅРё.",
)
async def remove_dict(
    payload: DictNameRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "remove_dict" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    xml_body = user_dict_xml.build_remove_user_dict_xml(payload.name)
    resp, final_action = await _send_xml(
        "remove_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    _require_completed_final_state(result, operation="remove")
    run_id = await _log_single_run(
        session,
        run_name="remove_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_status_response(
        operation="remove",
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/query-frame",
    summary="Р—Р°РїСЂРѕСЃРёС‚СЊ СЃС‚СЂСѓРєС‚СѓСЂСѓ СЃРїСЂР°РІРѕС‡РЅРёРєР°",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃС‚СЂСѓРєС‚СѓСЂСѓ/С„СЂРµР№Рј РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР°.",
)
async def query_frame(
    payload: Optional[DictNameRequest] = None,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with action_data and request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "query_frame" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    dict_name = payload.name if payload else None
    xml_body = user_dict_xml.build_query_user_dict_frame_xml(dict_name)
    resp, final_action = await _send_xml(
        "query_user_dict_frame",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    run_id = await _log_single_run(
        session,
        run_name="query_user_dict_frame",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_query_frame_response(
        dict_name=dict_name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/query",
    summary="Р—Р°РїСЂРѕСЃРёС‚СЊ РґР°РЅРЅС‹Рµ СЃРїСЂР°РІРѕС‡РЅРёРєР°",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ РґР°РЅРЅС‹Рµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ СЃРїСЂР°РІРѕС‡РЅРёРєР° Р±РµР· С„РёР»СЊС‚СЂР°С†РёРё.",
)
async def query_dict(
    payload: Optional[DictNameRequest] = None,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with action_data and request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "query_dict" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    dict_name = payload.name if payload else None
    xml_body = user_dict_xml.build_query_user_dict_xml(dict_name, prefer_v2=True)
    try:
        resp, final_action = await _send_xml(
            "query_user_dict",
            xml_body,
            accept_action=True,
            capture_final_action=True,
        )
    except HTTPException as exc:
        # РќР° СЂСЏРґРµ СЃР±РѕСЂРѕРє v2-С€Р°Р±Р»РѕРЅ РјРѕР¶РµС‚ РїР°РґР°С‚СЊ СЃ "Value out of range".
        # Р”РµР»Р°РµРј Р±РµР·РѕРїР°СЃРЅС‹Р№ fallback РЅР° v1 Р±РµР· РёР·РјРµРЅРµРЅРёСЏ API-РєРѕРЅС‚СЂР°РєС‚Р°.
        detail_text = str(exc.detail or "")
        if exc.status_code == 502 and "Value out of range" in detail_text:
            xml_body = user_dict_xml.build_query_user_dict_xml(dict_name, prefer_v2=False)
            resp, final_action = await _send_xml(
                "query_user_dict",
                xml_body,
                accept_action=True,
                capture_final_action=True,
            )
        else:
            raise
    result = _result(resp)
    _attach_action_payload(result, final_action)
    run_id = await _log_single_run(
        session,
        run_name="query_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_query_response(
        dict_name=dict_name,
        result=full_response,
        run_id=run_id,
        operation="query",
    )


@router.post(
    "/metainfo",
    summary="Р—Р°РїСЂРѕСЃРёС‚СЊ РјРµС‚Р°РёРЅС„РѕСЂРјР°С†РёСЋ",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ РјРµС‚Р°РґР°РЅРЅС‹Рµ СЃРїСЂР°РІРѕС‡РЅРёРєР°: РёРјСЏ, РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ, СЂР°Р·РјРµСЂ, РґР°С‚Сѓ РёР·РјРµРЅРµРЅРёСЏ.",
)
async def metainfo(
    payload: DictNameRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with action_data and request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "metainfo" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    candidates: List[str] = []
    for name in (payload.name, str(payload.name or "").split(".")[-1].strip()):
        nm = str(name or "").strip()
        if nm and nm not in candidates:
            candidates.append(nm)

    result: Dict[str, Any] = {}
    xml_body = ""
    for candidate in candidates:
        xml_candidate = user_dict_xml.build_query_user_dict_metainfo_xml(candidate)
        try:
            resp, final_action = await _send_xml(
                "query_user_dict_metainfo",
                xml_candidate,
                accept_action=True,
                capture_final_action=True,
            )
            result = _result(resp)
            _attach_action_payload(result, final_action)
        except HTTPException as exc:
            result = {"status": "fail", "description": str(exc.detail or "")}
        xml_body = xml_candidate
        if result.get("status") == "ok":
            break
    if result.get("status") != "ok":
        # Fallback dlya sborok, gde metainfo po imeni nedostupen dlya system dict:
        # podtverzhdaem slovar' cherez query_frame i vozvrashchaem kompatibilnyy compact-otvet.
        with suppress(HTTPException):
            frame_xml = user_dict_xml.build_query_user_dict_frame_xml(payload.name)
            frame_full = await _execute_xml_operation(
                alias_fallback="query_user_dict_frame",
                xml_body=frame_xml,
                operation="metainfo_query_frame_fallback",
                require_completed=True,
                final_action_timeout=INTERACTIVE_FINAL_ACTION_TIMEOUT_SEC,
                wait_non_system_response=False,
            )
            frame_compact = _compact_query_frame_response(
                dict_name=payload.name,
                result=frame_full,
                run_id=0,
            )
            frames = frame_compact.get("frames")
            if isinstance(frames, list) and frames:
                requested = str(payload.name or "").strip().lower()
                hit: Optional[Dict[str, Any]] = None
                for fr in frames:
                    if not isinstance(fr, dict):
                        continue
                    fr_name = str(fr.get("name_real") or fr.get("name") or "").strip()
                    if not fr_name:
                        continue
                    fr_lower = fr_name.lower()
                    if (
                        fr_lower == requested
                        or requested.endswith(fr_lower)
                        or fr_lower.endswith(requested)
                    ):
                        hit = fr
                        break
                if hit is None and isinstance(frames[0], dict):
                    hit = frames[0]
                if isinstance(hit, dict):
                    hit_display_name = str(hit.get("name") or hit.get("name_real") or payload.name)
                    result = {
                        "status": "ok",
                        "report_code_name": "DONE",
                        "description": "",
                        "operation": "metainfo",
                        "dict_name": hit_display_name,
                        "final_state": "completed",
                        "dict_id": hit.get("id"),
                        "dict_name_value": hit_display_name,
                        "dict_size": None,
                        "dict_last_modified": None,
                        "fallback_source": "query_frame",
                    }
    run_id = await _log_single_run(
        session,
        run_name="query_user_dict_metainfo",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_metainfo_response(
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/select-fields",
    summary="Select Dictionary Rows",
    description=(
        "Selects rows from a dictionary with filters, sorting, and pagination. "
        "Default response is compact; use verbose=true for full ISHD payload."
    ),
)
async def select_fields(
    payload: SelectFieldsRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with action_data and request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "select_fields" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    full_response = await _send_select_fields_with_fallback(
        dict_name=payload.name,
        filters=[f.model_dump() for f in payload.filters] if payload.filters else None,
        order_by=[o.model_dump() for o in payload.order_by] if payload.order_by else None,
        limit=payload.limit,
        offset=payload.offset,
        expand_links=payload.expand_links,
    )
    run_id = await _log_single_run(
        session,
        run_name="select_fields_user_dict_v1",
        xml_body=str(full_response.get("request_xml") or ""),
        result=full_response,
    )
    full_response = full_response | {"run_id": run_id}
    if verbose:
        return full_response
    return _compact_select_fields_response(
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/insert",
    summary="Р”РѕР±Р°РІРёС‚СЊ СЃС‚СЂРѕРєРё",
    description="Р”РѕР±Р°РІР»СЏРµС‚ РѕРґРЅСѓ РёР»Рё РЅРµСЃРєРѕР»СЊРєРѕ СЃС‚СЂРѕРє РІ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёР№ СЃРїСЂР°РІРѕС‡РЅРёРє.",
)
async def insert_rows(
    payload: InsertRowsRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "insert_rows" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    xml_body = user_dict_xml.build_insert_user_dict_xml(payload.name, payload.rows)
    resp, final_action = await _send_xml(
        "insert_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    _require_completed_final_state(result, operation="insert")
    _enhance_insert_type_mismatch_description(result, payload.rows)
    run_id = await _log_single_run(
        session,
        run_name="insert_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_status_response(
        operation="insert",
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
        extra={"inserted_count": len(payload.rows)},
    )


@router.post(
    "/search",
    summary="Search Rows",
    description=(
        "Searches rows by filters. "
        "Default response is compact; use verbose=true for full ISHD payload."
    ),
)
async def search(
    payload: FiltersRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with action_data and request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "search" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    xml_body = user_dict_xml.build_query_single_user_dict_xml(
        payload.name,
        [f.model_dump() for f in payload.filters],
    )
    resp, final_action = await _send_xml(
        "query_single_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    result.setdefault("tables", [])
    result.setdefault("found_count", 0)
    run_id = await _log_single_run(
        session,
        run_name="query_single_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_search_response(
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
    )


@router.post(
    "/file/upload",
    summary="Upload File To Dictionary Field",
    description=(
        "Updates one row (row_id) and writes file bytes into selected column. "
        "Supported payload formats: plain base64 or data:*;base64,..."
    ),
)
async def upload_file_to_dict(
    payload: UploadFileRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml.",
    ),
):
    effective_row_id = _normalize_uuid_or_raise(payload.row_id)
    requested_column_name = str(payload.column or "").strip()
    if not requested_column_name:
        raise HTTPException(status_code=400, detail="column must not be empty.")
    filename = str(payload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename must not be empty.")

    frame_columns = await _query_frame_columns(payload.name)
    available_columns = frame_columns.get("columns", [])
    file_columns = frame_columns.get("file_columns", [])
    if available_columns:
        column_name = _resolve_column_name_case_insensitive(requested_column_name, available_columns)
        if not column_name:
            cols_preview = ", ".join(available_columns[:20]) if available_columns else "<empty>"
            file_cols_preview = ", ".join(file_columns[:20]) if file_columns else "<not detected>"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Column '{requested_column_name}' not found in dictionary frame. "
                    f"Use exact column name from Query Frame/Search. "
                    f"Available columns: {cols_preview}. "
                    f"Detected file columns: {file_cols_preview}."
                ),
            )
    else:
        # Some Paragraph builds return empty frame metadata for user dicts.
        # Try resolving by real row columns first; fallback to requested name for compatibility.
        column_name = requested_column_name
        try:
            probe_row = await _query_row_by_uuid(payload.name, effective_row_id)
            if isinstance(probe_row, dict) and probe_row:
                resolved = _resolve_column_name_case_insensitive(requested_column_name, list(probe_row.keys()))
                if resolved:
                    column_name = resolved
        except HTTPException:
            pass

    raw_data = _decode_base64_payload(payload.data_base64)
    normalized_base64 = base64.b64encode(raw_data).decode("ascii")
    full: Optional[Dict[str, Any]] = None
    last_error: Optional[HTTPException] = None
    last_verify_error_detail: Optional[str] = None
    attempt_debug: List[Dict[str, Any]] = []

    for file_param_type in ("binary_param", "input_file"):
        xml_body = user_dict_xml.build_update_user_dict_xml(
            dict_name=payload.name,
            row_id=effective_row_id,
            values={
                column_name: {
                    "filename": filename,
                    "data_base64": normalized_base64,
                    "_file_param_type": file_param_type,
                }
            },
        )
        try:
            full = await _execute_xml_operation(
                alias_fallback="update_user_dict",
                xml_body=xml_body,
                operation="upload_file",
                require_completed=True,
            )
            attempt_debug.append(
                {
                    "param_type": file_param_type,
                    "transport": "ok",
                    "update_status": str(full.get("status") or ""),
                    "update_description": str(full.get("description") or "").strip(),
                }
            )
            verify = await _wait_until_file_visible(
                dict_name=payload.name,
                row_id=effective_row_id,
                column_name=column_name,
            )
            if bool(verify.get("ok")):
                attempt_debug[-1]["verify_ok"] = True
                break
            last_value = verify.get("last_value")
            checks = int(verify.get("checks") or 0)
            resolved_column = str(verify.get("resolved_column") or column_name)
            available_columns = verify.get("available_columns")
            visible_other_file_columns = verify.get("visible_other_file_columns")
            visible_other_file_previews = verify.get("visible_other_file_previews")
            if not isinstance(available_columns, list):
                available_columns = []
            if not isinstance(visible_other_file_columns, list):
                visible_other_file_columns = []
            if not isinstance(visible_other_file_previews, dict):
                visible_other_file_previews = {}
            attempt_debug[-1]["verify_ok"] = False
            attempt_debug[-1]["verify_checks"] = checks
            attempt_debug[-1]["verify_resolved_column"] = resolved_column
            attempt_debug[-1]["verify_available_columns"] = available_columns
            attempt_debug[-1]["verify_value_preview"] = _short_preview(last_value)
            attempt_debug[-1]["verify_visible_other_file_columns"] = visible_other_file_columns
            last_verify_error_detail = (
                f"Upload executed, but column '{column_name}' is still empty or unresolved "
                f"after {checks} checks (~{int(UPLOAD_FILE_VERIFY_TIMEOUT_SEC)}s). "
                f"Resolved column: '{resolved_column}'. "
                f"Available columns: {available_columns}. "
                f"Value preview: {_short_preview(last_value)}. "
                f"Source: Paragraph API/Integrator (request accepted, file not materialized). "
                f"Check Paragraph file-transfer/export settings, output path, and directory accessibility. "
                f"Checklist: "
                f"(1) ensure the same row/column is edited in Paragraph UI; "
                f"(2) ensure file export/upload path exists and is writable by integrator service; "
                f"(3) ensure integrator and ESB services are running and authorized; "
                f"(4) retry with a small ASCII filename to exclude filename-encoding issues; "
                f"(5) verify row value in /dicts/search immediately after upload."
            )
            if visible_other_file_columns:
                last_verify_error_detail += (
                    f" Detected visible file-like value(s) in other column(s): "
                    f"{visible_other_file_columns}. "
                    f"Previews: {visible_other_file_previews}."
                )
            full = None
        except HTTPException as exc:
            last_error = exc
            attempt_debug.append(
                {
                    "param_type": file_param_type,
                    "transport": "error",
                    "http_status": int(exc.status_code),
                    "http_detail": str(exc.detail),
                }
            )
            continue

    if full is None:
        debug_parts: List[str] = []
        for item in attempt_debug:
            p = str(item.get("param_type") or "?")
            if item.get("transport") == "ok":
                debug_parts.append(
                    f"{p}: update={item.get('update_status')}, "
                    f"verify_ok={item.get('verify_ok')}, checks={item.get('verify_checks')}, "
                    f"resolved_column={item.get('verify_resolved_column')}, "
                    f"value={item.get('verify_value_preview')}"
                )
            else:
                debug_parts.append(
                    f"{p}: http={item.get('http_status')} detail={item.get('http_detail')}"
                )
        debug_suffix = f" attempts=[{' | '.join(debug_parts)}]" if debug_parts else ""
        if last_verify_error_detail:
            raise HTTPException(status_code=409, detail=last_verify_error_detail + debug_suffix)
        if last_error is not None:
            raise last_error
        raise HTTPException(status_code=500, detail="Upload operation failed before completion.")

    compact = _compact_status_response(
        operation="upload_file",
        dict_name=payload.name,
        result=full,
        run_id=0,
        extra={
            "row_id": effective_row_id,
            "column": column_name,
            "filename": filename,
            "size_bytes": len(raw_data),
        },
    )
    if verbose:
        return full
    return compact


@router.post(
    "/file/download",
    summary="РЎРєР°С‡Р°С‚СЊ С„Р°Р№Р» РёР· Р·РЅР°С‡РµРЅРёСЏ РєРѕР»РѕРЅРєРё",
    description=(
        "РС‰РµС‚ СЃС‚СЂРѕРєСѓ РїРѕ row_id Рё РІРѕР·РІСЂР°С‰Р°РµС‚ С„Р°Р№Р» РёР· СѓРєР°Р·Р°РЅРЅРѕР№ РєРѕР»РѕРЅРєРё. "
        "РџРѕРґРґРµСЂР¶РёРІР°РµС‚ binary_param Рё input_file."
    ),
)
async def download_file_from_dict(
    payload: DownloadFileRequest,
):
    effective_row_id = _normalize_uuid_or_raise(payload.row_id)
    column_name = str(payload.column or "").strip()
    if not column_name:
        raise HTTPException(status_code=400, detail="column must not be empty.")
    selected_row: Optional[Dict[str, Any]] = None
    ishd_error: Optional[HTTPException] = None

    try:
        selected_row = await _query_row_by_uuid(
            payload.name,
            effective_row_id,
            include_select_fallback=False,
        )
    except HTTPException as exc:
        ishd_error = exc
        selected_row = None

    file_blob: Optional[Dict[str, Any]] = None
    if isinstance(selected_row, dict):
        if column_name not in selected_row:
            resolved = _resolve_column_name_case_insensitive(column_name, list(selected_row.keys()))
            if resolved:
                column_name = resolved
    if not isinstance(selected_row, dict) or column_name not in selected_row:
        if ishd_error is not None:
            raise ishd_error
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' with file payload not found in selected row.")

    file_ids = _extract_file_id_candidates_from_value(selected_row.get(column_name))
    if not file_ids:
        # Dlya sebya: dlya system dict payload faila inogda est' tolko v full query.
        with suppress(HTTPException):
            row_full = await _query_row_by_uuid_from_full_query(payload.name, effective_row_id)
            if isinstance(row_full, dict):
                selected_row = row_full
                if column_name not in selected_row:
                    resolved = _resolve_column_name_case_insensitive(column_name, list(selected_row.keys()))
                    if resolved:
                        column_name = resolved
                file_ids = _extract_file_id_candidates_from_value(selected_row.get(column_name))
    if not file_ids:
        raise HTTPException(
            status_code=404,
            detail=f"No file_id found in value of column '{column_name}'.",
        )

    file_blob: Optional[Dict[str, Any]] = None

    # Быстрый локальный путь: если в значении уже есть path/base64, не ждём documentfilesget.
    with suppress(HTTPException):
        file_blob = _extract_file_blob_from_value(
            selected_row.get(column_name),
            file_index=payload.file_index,
        )

    if file_blob is None:
        try:
            file_blob = await _download_file_blob_via_documentfilesget(
                file_ids=file_ids,
                file_index=payload.file_index,
                max_id_variants=2,
                per_request_timeout_sec=3.0,
            )
        except HTTPException:
            if file_blob is None:
                with suppress(HTTPException):
                    file_blob = await _download_file_blob_from_paragraph_db_by_ai_id(
                        row_value=selected_row.get(column_name),
                        dict_name=payload.name,
                        column_name=column_name,
                        file_index=payload.file_index,
                    )
            if file_blob is None:
                file_blob = await _download_file_blob_from_paragraph_db(
                    dict_name=payload.name,
                    row_id=effective_row_id,
                    column_name=column_name,
                    file_index=payload.file_index,
                )

    effective_column_name = column_name
    filename = file_blob.get("filename") or f"{payload.name}_{effective_column_name}_{effective_row_id}.bin"
    media_type = _guess_media_type_from_filename(filename)
    ascii_fallback = re.sub(r'[^A-Za-z0-9._-]+', "_", str(filename or "").strip()).strip("._")
    if not ascii_fallback:
        ascii_fallback = "download.bin"
    filename_star = quote(str(filename), safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{filename_star}'
        )
    }
    return Response(content=file_blob["bytes"], media_type=media_type, headers=headers)


@router.post(
    "/update",
    summary="РћР±РЅРѕРІРёС‚СЊ СЃС‚СЂРѕРєСѓ",
    description="РћР±РЅРѕРІР»СЏРµС‚ СЃС‚СЂРѕРєСѓ РїРѕ row_id.",
)
async def update_row(
    payload: UpdateRowRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Keep strong UUID validation but avoid pre-check by search on uuid:
    # some Paragraph builds may return broad matches for that check.
    # The update request itself is sent with explicit table_row_uuid.
    # Dlya sebya: endpoint "update_row" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    effective_row_id = _normalize_uuid_or_raise(payload.row_id)

    xml_body = user_dict_xml.build_update_user_dict_xml(
        dict_name=payload.name,
        row_id=effective_row_id,
        values=payload.values,
    )
    resp, final_action = await _send_xml(
        "update_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    _require_completed_final_state(result, operation="update")
    run_id = await _log_single_run(
        session,
        run_name="update_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {"request_xml": xml_body, "run_id": run_id}
    if verbose:
        return full_response
    return _compact_status_response(
        operation="update",
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
        extra={"row_id": effective_row_id},
    )


@router.post(
    "/remove-rows",
    summary="РЈРґР°Р»РёС‚СЊ СЃС‚СЂРѕРєРё",
    description="РЈРґР°Р»СЏРµС‚ СЃС‚СЂРѕРєРё РїРѕ row_ids РёР»Рё С„РёР»СЊС‚СЂР°Рј.",
)
async def remove_rows(
    payload: RemoveRowsRequest,
    verbose: bool = Query(
        default=False,
        description="Return full ISHD payload with request_xml and debug fields.",
    ),
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "remove_rows" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    if not payload.row_ids and not payload.filters:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of row_ids or filters",
        )
    if payload.row_ids and payload.filters:
        raise HTTPException(
            status_code=400,
            detail=(
                "Use either row_ids or filters in one request. "
                "Combining both is unsafe and may delete more rows than expected."
            ),
        )

    resolved_row_ids: List[str] = []
    resolved_source = "payload_row_ids" if payload.row_ids else "filters"
    remove_filters: Optional[List[Dict[str, str]]] = None
    seen: set[str] = set()
    for rid in payload.row_ids or []:
        for v in _row_id_variants(rid):
            if v in seen:
                continue
            seen.add(v)
            resolved_row_ids.append(v)

    filters_payload = [f.model_dump() for f in payload.filters] if payload.filters else None

    if filters_payload and not resolved_row_ids:
        # Pre-check matched rows via query_single_user_dict.
        # Then perform delete by filters only (as in ESBMonitor flow).
        search_xml = user_dict_xml.build_query_single_user_dict_xml(
            payload.name,
            filters_payload,
        )
        search_resp, search_final_action = await _send_xml(
            "query_single_user_dict",
            search_xml,
            accept_action=True,
            capture_final_action=True,
        )
        search_result = _result(search_resp)
        _attach_action_payload(search_result, search_final_action)
        if search_result["status"] != "ok":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Failed to resolve rows by filters before delete",
                    "search_result": search_result,
                },
            )

        matched_tables = search_result.get("tables", [])
        matched_count = sum(len(t.get("rows", [])) for t in matched_tables)
        matched_row_ids = _extract_row_ids_from_tables(matched_tables)

        if matched_count <= 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": (
                        "Filters matched 0 rows. Delete is blocked to prevent "
                        "accidental full dictionary cleanup."
                    ),
                    "search_result": search_result,
                },
            )

        if matched_count > 1 and not payload.allow_many:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": (
                        "Filters matched multiple rows. "
                        "Narrow filters or set allow_many=true for bulk delete."
                    ),
                    "matched_count": matched_count,
                    "matched_row_ids": matched_row_ids,
                },
            )

        # For single-row delete, send a strict uuid filter to avoid broad cleanup.
        if matched_count == 1 and matched_row_ids:
            remove_filters = [
                {
                    "column": "uuid",
                    "condition": DEFAULT_FILTER_CONDITION,
                    "value": matched_row_ids[0],
                }
            ]
            resolved_source = "filters_query_single_uuid"
        else:
            remove_filters = filters_payload
            resolved_source = "filters_original"

    if not resolved_row_ids and not remove_filters:
        raise HTTPException(
            status_code=400,
            detail="No delete target resolved (row_ids or filters).",
        )

    if resolved_row_ids and remove_filters:
        raise HTTPException(
            status_code=400,
            detail=(
                "Internal safety guard: both row_ids and filters prepared. "
                "Delete request is blocked."
            ),
        )

    if resolved_row_ids:
        xml_body = user_dict_xml.build_remove_from_user_dict_xml(
            dict_name=payload.name,
            row_ids=resolved_row_ids,
            filters=None,
        )
    else:
        xml_body = user_dict_xml.build_remove_from_user_dict_xml(
            dict_name=payload.name,
            row_ids=None,
            filters=remove_filters,
        )

    resp, final_action = await _send_xml(
        "remove_from_user_dict",
        xml_body,
        accept_action=True,
        capture_final_action=True,
    )
    result = _result(resp)
    _attach_action_payload(result, final_action)
    _require_completed_final_state(result, operation="remove_rows")
    run_id = await _log_single_run(
        session,
        run_name="remove_from_user_dict",
        xml_body=xml_body,
        result=result,
    )
    full_response = result | {
        "request_xml": xml_body,
        "run_id": run_id,
        "resolved_row_ids": resolved_row_ids,
        "resolved_row_ids_source": resolved_source,
        "remove_filters_used": remove_filters or [],
    }
    if verbose:
        return full_response
    return _compact_status_response(
        operation="remove_rows",
        dict_name=payload.name,
        result=full_response,
        run_id=run_id,
        extra={
            "deleted_count": len(resolved_row_ids),
            "deleted_row_ids": resolved_row_ids,
            "delete_mode": resolved_source,
            "filters_used": remove_filters or [],
        },
    )


@router.get(
    "/autotest/dicts",
    summary="РЎРїРёСЃРѕРє СЃРїСЂР°РІРѕС‡РЅРёРєРѕРІ РґР»СЏ Р°РІС‚РѕС‚РµСЃС‚Р°",
    description=(
        "Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє СЃРїСЂР°РІРѕС‡РЅРёРєРѕРІ РёР· РРЁР” user-dicts API РґР»СЏ РІС‹Р±СЂР°РЅРЅРѕР№ С†РµР»Рё."
    ),
)
async def autotest_dicts_list() -> Dict[str, Any]:
    # Dlya sebya: glavnaya doroga - cherez ISHD (trebovanie "autotest tolko user-dicts").
    target_id = _current_target_id()
    cache_source = "autotest_dicts"
    cached = await _autotest_dicts_cache_get(target_id, cache_source)
    if cached:
        return {
            "target_id": target_id,
            "target_name": _current_target_name(),
            "count": len(cached),
            "items": cached,
            "source": "cache",
            "notes": [f"cached (ttl={int(AUTOTEST_DICTS_CACHE_TTL_SEC)}s)"],
        }

    errors: List[str] = []
    items: List[Dict[str, str]] = []

    try:
        xml_body = user_dict_xml.build_query_user_dict_frame_xml(None)
        resp, final_action = await _send_xml(
            "query_user_dict_frame",
            xml_body,
            accept_action=True,
            capture_final_action=True,
            final_action_timeout=AUTOTEST_DICTS_LIST_TIMEOUT_SEC,
        )
        result = _result(resp)
        _attach_action_payload(result, final_action)
        items = _extract_dict_refs_from_query_frame_action(result.get("action_data"))
        if not items:
            if not result.get("action_data"):
                errors.append("ISHD query_user_dict_frame: final action timeout")
            errors.append("ISHD query_user_dict_frame returned empty user_table_frame")
    except HTTPException as e:
        errors.append(f"ISHD frame: {e.detail}")
    except Exception as e:
        errors.append(f"ISHD frame unexpected error: {e}")

    try:
        if not items:
            xml_body = user_dict_xml.build_query_user_dict_xml(None, prefer_v2=False)
            resp, final_action = await _send_xml(
                "query_user_dict",
                xml_body,
                accept_action=True,
                capture_final_action=True,
                final_action_timeout=AUTOTEST_DICTS_LIST_TIMEOUT_SEC,
            )
            result = _result(resp)
            _attach_action_payload(result, final_action)
            items = _extract_dict_refs_from_query_action(result.get("action_data"))
            if not items:
                if not result.get("action_data"):
                    errors.append("ISHD query_user_dict: final action timeout")
                errors.append("ISHD query_user_dict returned empty user_tables")
    except HTTPException as e:
        errors.append(f"ISHD query: {e.detail}")
    except Exception as e:
        errors.append(f"ISHD query unexpected error: {e}")

    try:
        if not items:
            xml_body = user_dict_xml.build_query_user_dict_xml(None, prefer_v2=True)
            resp, final_action = await _send_xml(
                "query_user_dict",
                xml_body,
                accept_action=True,
                capture_final_action=True,
                final_action_timeout=AUTOTEST_DICTS_LIST_TIMEOUT_SEC,
            )
            result = _result(resp)
            _attach_action_payload(result, final_action)
            items = _extract_dict_refs_from_query_action(result.get("action_data"))
            if not items:
                if not result.get("action_data"):
                    errors.append("ISHD query_user_dict(v2): final action timeout")
                errors.append("ISHD query_user_dict(v2) returned empty user_tables")
    except HTTPException as e:
        errors.append(f"ISHD query(v2): {e.detail}")
    except Exception as e:
        errors.append(f"ISHD query(v2) unexpected error: {e}")

    if not items:
        stale_cached = await _autotest_dicts_cache_get(target_id, cache_source, allow_stale=True)
        if stale_cached:
            return {
                "target_id": target_id,
                "target_name": _current_target_name(),
                "count": len(stale_cached),
                "items": stale_cached,
                "source": "cache_stale",
                "notes": errors + ["returned stale cache because ISHD list load failed"],
            }
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to load dictionaries list from ISHD user-dicts API. "
                + " | ".join(errors)
            ),
        )

    await _autotest_dicts_cache_set(target_id, cache_source, items)

    return {
        "target_id": target_id,
        "target_name": _current_target_name(),
        "count": len(items),
        "items": items,
        "source": "ishd",
        "notes": errors,
    }


def _autotest_error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            return detail
        return str(detail)
    return str(exc)


async def _run_autotest_job_background(
    *,
    job_id: str,
    payload: AutoTestRunRequest,
    target_id: Optional[int],
) -> None:
    run_lock = _get_autotest_run_lock(target_id)
    if run_lock.locked():
        await _autotest_job_mark_finished(
            job_id,
            status="failed",
            error="Autotest already running for this target",
        )
        return

    await _autotest_job_update(job_id, status="running")

    async with run_lock:
        async with async_session_maker() as session:
            runtime_target: Optional[RuntimeTarget] = None
            target_lock: Optional[asyncio.Lock] = None
            client: Optional[IshdClient] = None
            token_target = None
            token_client = None

            try:
                if target_id is not None:
                    runtime_target = await resolve_runtime_target(session, target_id)
                    target_lock = _get_target_runtime_lock(runtime_target)
                    await target_lock.acquire()
                    # Reuse cached target client to avoid extra login flaps in background autotest.
                    client = _get_or_create_target_cached_client(runtime_target)
                    await _autotest_connect_with_retry(
                        client=client,
                        runtime_target=runtime_target,
                        job_id=job_id,
                    )

                token_target = _target_ctx.set(runtime_target)
                token_client = _target_client_ctx.set(client)

                await _autotest_job_update(
                    job_id,
                    target_name=(runtime_target.name if runtime_target else "env-default"),
                    status="running",
                )

                async def _progress(event: Dict[str, Any]) -> None:
                    await _autotest_job_progress(job_id, event)

                report = await _run_user_dict_autotest(
                    payload,
                    session,
                    progress_cb=_progress,
                )
                report["report_url"] = f"/dicts/autotest/reports/{report['run_id']}"
                report["target_id"] = target_id
                report["target_name"] = runtime_target.name if runtime_target else "env-default"

                await _autotest_job_update(
                    job_id,
                    run_id=report["run_id"],
                    report_url=report["report_url"],
                    report=report,
                )

                failed = int(((report.get("summary") or {}).get("failed") or 0))
                await _autotest_job_mark_finished(
                    job_id,
                    status="failed" if failed > 0 else "passed",
                    error=None,
                )
            except asyncio.CancelledError:
                await session.rollback()
                await _autotest_job_progress(
                    job_id,
                    {
                        "event": "finished",
                        "status": "cancelled",
                        "message": "Autotest cancelled by user",
                    },
                )
                await _autotest_job_mark_finished(
                    job_id,
                    status="cancelled",
                    error="Autotest cancelled by user",
                )
                return
            except Exception as exc:
                await session.rollback()
                error_text = _autotest_error_text(exc)
                await _autotest_job_progress(
                    job_id,
                    {
                        "event": "finished",
                        "status": "failed",
                        "message": error_text,
                    },
                )
                await _autotest_job_mark_finished(
                    job_id,
                    status="failed",
                    error=error_text,
                )
                logger.exception("Autotest background job failed (job_id=%s): %s", job_id, error_text)
            finally:
                if token_client is not None:
                    _target_client_ctx.reset(token_client)
                if token_target is not None:
                    _target_ctx.reset(token_target)
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception as e:
                        logger.warning("ISHD disconnect warning in autotest job %s: %s", job_id, e)
                if target_lock is not None and target_lock.locked():
                    target_lock.release()


@router.post(
    "/autotest/run-async",
    summary="Р—Р°РїСѓСЃС‚РёС‚СЊ Р°РІС‚РѕС‚РµСЃС‚ user-dicts (async)",
    description="Р—Р°РїСѓСЃРєР°РµС‚ Р·Р°РґР°С‡Сѓ РІ С„РѕРЅРµ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ job_id РґР»СЏ РѕРїСЂРѕСЃР° РїСЂРѕРіСЂРµСЃСЃР°.",
)
async def autotest_run_async(
    payload: AutoTestRunRequest,
) -> Dict[str, Any]:
    target_id = _current_target_id()
    run_lock = _get_autotest_run_lock(target_id)
    if run_lock.locked():
        running_locked = await _autotest_job_find_running(target_id)
        if running_locked is not None:
            return {"job": running_locked, "already_running": True}
        raise HTTPException(
            status_code=409,
            detail="Autotest already running for this target",
        )

    running = await _autotest_job_find_running(target_id)
    if running is not None:
        return {"job": running, "already_running": True}

    job = await _autotest_job_create(
        target_id=target_id,
        target_name=_current_target_name(),
        payload=payload,
    )
    task = asyncio.create_task(
        _run_autotest_job_background(
            job_id=str(job["job_id"]),
            payload=payload,
            target_id=target_id,
        )
    )
    await _autotest_job_set_task(str(job["job_id"]), task)
    return {"job": job, "already_running": False}


@router.get(
    "/autotest/jobs/current",
    summary="РўРµРєСѓС‰Р°СЏ async-Р·Р°РґР°С‡Р° РїРѕ С†РµР»Рё",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ Р°РєС‚РёРІРЅСѓСЋ async-Р·Р°РґР°С‡Сѓ Р°РІС‚РѕС‚РµСЃС‚Р° РґР»СЏ РІС‹Р±СЂР°РЅРЅРѕР№ С†РµР»Рё, РµСЃР»Рё РѕРЅР° РµСЃС‚СЊ.",
)
async def autotest_job_current() -> Dict[str, Any]:
    job = await _autotest_job_find_running(_current_target_id())
    return {"job": job}


@router.get(
    "/autotest/jobs/{job_id}",
    summary="РЎС‚Р°С‚СѓСЃ async-Р·Р°РґР°С‡Рё Р°РІС‚РѕС‚РµСЃС‚Р°",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСѓС‰РёР№ РїСЂРѕРіСЂРµСЃСЃ Рё С„РёРЅР°Р»СЊРЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚ async-Р·Р°РґР°С‡Рё.",
)
async def autotest_job_get(job_id: str) -> Dict[str, Any]:
    job = await _autotest_job_get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Autotest job not found")
    return {"job": job}


@router.post(
    "/autotest/jobs/{job_id}/cancel",
    summary="Остановить async-задачу автотеста",
    description="Запрашивает остановку текущей async-задачи автотеста по job_id.",
)
async def autotest_job_cancel(job_id: str) -> Dict[str, Any]:
    job = await _autotest_job_cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Autotest job not found")
    return {"job": job, "cancel_requested": bool(job.get("cancel_requested"))}

@router.post(
    "/autotest/run",
    summary="Р—Р°РїСѓСЃС‚РёС‚СЊ Р°РІС‚РѕС‚РµСЃС‚ user-dicts",
    description=(
        "РџРѕР»РЅС‹Р№ РїСЂРѕРіРѕРЅ РїРѕ РїСЂРµРґСѓСЃС‚Р°РЅРѕРІР»РµРЅРЅРѕРјСѓ СЃРїСЂР°РІРѕС‡РЅРёРєСѓ (read-only С€Р°РіРё) "
        "Рё Р±РµР·РѕРїР°СЃРЅС‹Р№ CRUD-СЃС†РµРЅР°СЂРёР№ РЅР° РІСЂРµРјРµРЅРЅРѕРј СЃРїСЂР°РІРѕС‡РЅРёРєРµ."
    ),
)
async def autotest_run(
    payload: AutoTestRunRequest,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    # Dlya sebya: edinaya knopka \"zapustit vse\" dlya rukovoditelya.
    target_id = _current_target_id()
    run_lock = _get_autotest_run_lock(target_id)
    if run_lock.locked():
        raise HTTPException(
            status_code=409,
            detail=(
                "Autotest already running for this target. "
                "Wait until current run finishes and refresh report history."
            ),
        )

    async with run_lock:
        report = await _run_user_dict_autotest(payload, session)
    report["report_url"] = f"/dicts/autotest/reports/{report['run_id']}"
    report["target_id"] = target_id
    report["target_name"] = _current_target_name()
    return report


@router.get(
    "/autotest/reports",
    summary="РЎРїРёСЃРѕРє РѕС‚С‡РµС‚РѕРІ Р°РІС‚РѕС‚РµСЃС‚Р°",
    description="РљРѕСЂРѕС‚РєРёР№ СЃРїРёСЃРѕРє РїРѕСЃР»РµРґРЅРёС… РїСЂРѕРіРѕРЅРѕРІ Р°РІС‚РѕС‚РµСЃС‚Р°.",
)
async def autotest_reports_list(
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    # Dlya sebya: eto mini-zhurnal zapuskov dlya paneli v UI.
    items = autotest_reports.list_reports(limit=limit)
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("ui_summary"):
            item["ui_summary"] = _build_ui_autotest_summary(item)
    return {"count": len(items), "items": items}


@router.get(
    "/autotest/reports/{run_id}",
    summary="РћРґРёРЅ РѕС‚С‡РµС‚ Р°РІС‚РѕС‚РµСЃС‚Р°",
    description="РџРѕР»РЅС‹Р№ JSON-РѕС‚С‡РµС‚ РїРѕ run_id.",
)
async def autotest_report_get(run_id: str) -> Dict[str, Any]:
    # Dlya sebya: po kliku na progon pokazhite vse shagi s oshibkami i request_xml.
    report = autotest_reports.load_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Autotest report not found")
    if not report.get("ui_summary"):
        report["ui_summary"] = _build_ui_autotest_summary(report)
    return report


@router.get(
    "/autotest/reports/{run_id}/download",
    summary="Download full autotest report JSON",
    description="Returns raw report JSON as downloadable file.",
)
async def autotest_report_download(run_id: str) -> FileResponse:
    path = autotest_reports.get_report_path(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Autotest report not found")
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=f"{run_id}.json",
    )


@router.get(
    "/autotest/reports/{run_id}/artifacts/{artifact_id}/download",
    summary="Download report artifact file",
    description="Downloads file artifact attached to autotest report.",
)
async def autotest_report_artifact_download(run_id: str, artifact_id: str) -> FileResponse:
    report = autotest_reports.load_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Autotest report not found")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        raise HTTPException(status_code=404, detail="Artifact not found")
    selected: Optional[Dict[str, Any]] = None
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == artifact_id:
            selected = item
            break
    if selected is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    filename = str(selected.get("filename") or "").strip() or f"{artifact_id}.bin"
    path = autotest_reports.get_artifact_path(run_id, artifact_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Artifact file not found")
    media_type = str(selected.get("content_type") or "").strip() or _guess_media_type_from_filename(filename)
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=filename,
    )


@router.delete(
    "/autotest/reports/{run_id}",
    summary="Delete autotest report",
    description="Deletes report file and removes run from history list.",
)
async def autotest_report_delete(run_id: str) -> Dict[str, Any]:
    deleted = autotest_reports.delete_report(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Autotest report not found")
    return {"status": "ok", "run_id": run_id, "deleted": True}


@router.post(
    "/run-all",
    summary="РџСЂРѕРіРЅР°С‚СЊ РїРѕР»РЅС‹Р№ СЃС†РµРЅР°СЂРёР№",
    description="Р’С‹РїРѕР»РЅСЏРµС‚ СЃС†РµРЅР°СЂРёР№ create->insert->search->select->query->metainfo->query-frame->remove-rows->remove.",
)
async def run_all(payload: RunAllRequest, session: AsyncSession = Depends(get_session)):
    # Dlya sebya: endpoint "run_all" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    run_id = await test_run_logger.create_run(session, "run_all_user_dicts")
    step = 1

    rows = [{"name": "Ivan"}]
    results: List[Dict[str, Any]] = []

    try:
        xml_body = user_dict_xml.build_create_user_dict_xml(payload.name)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="create",
                alias="create_user_dict_v1",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_insert_user_dict_xml(payload.name, rows)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="insert",
                alias="insert_user_dict",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_query_single_user_dict_xml(
            payload.name,
            [{"column": "name", "condition": DEFAULT_FILTER_CONDITION, "value": "Ivan"}],
        )
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="search",
                alias="query_single_user_dict",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_select_fields_user_dict_xml(payload.name)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="select_fields",
                alias="select_fields_user_dict_v1",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_query_user_dict_xml(payload.name)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="query",
                alias="query_user_dict",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_query_user_dict_metainfo_xml(payload.name)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="metainfo",
                alias="query_user_dict_metainfo",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_query_user_dict_frame_xml(payload.name)
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="query_frame",
                alias="query_user_dict_frame",
                xml_body=xml_body,
            )
        )
        step += 1

        xml_body = user_dict_xml.build_remove_from_user_dict_xml(
            payload.name,
            filters=[{"column": "name", "condition": DEFAULT_FILTER_CONDITION, "value": "Ivan"}],
        )
        results.append(
            await _run_and_log(
                session,
                run_id,
                step,
                title="remove_rows",
                alias="remove_from_user_dict",
                xml_body=xml_body,
            )
        )
        step += 1

        if not payload.keep:
            xml_body = user_dict_xml.build_remove_user_dict_xml(payload.name)
            results.append(
                await _run_and_log(
                    session,
                    run_id,
                    step,
                    title="remove_dict",
                    alias="remove_user_dict",
                    xml_body=xml_body,
                )
            )
            step += 1

        final_status = "success" if all(r["status"] == "ok" for r in results) else "failed"
        await test_run_logger.finish_run(session, run_id, final_status)
        await session.commit()
    except HTTPException:
        await test_run_logger.finish_run(session, run_id, "failed")
        await session.commit()
        raise
    except Exception as e:
        await test_run_logger.finish_run(session, run_id, "failed")
        await session.commit()
        raise HTTPException(status_code=500, detail=str(e))

    return {"run_id": run_id, "results": results}



