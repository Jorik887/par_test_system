import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import settings
from src.core.db import get_session
from src.ishd.client import IshdClient
from src.models.test_target import TestTarget
from src.services import paragraph_rest
from src.services.paragraph_rest import ParagraphRestError
from src.services import targets as target_service
SAFE_ISHD_REQUEST_TIMEOUT_SEC = 8.0
SAFE_ISHD_DOC_RESPONSE_TIMEOUT_SEC = 35.0
SAFE_ISHD_ACTION_DIRECT_TIMEOUT_SEC = 1.0
SAFE_ISHD_ACTION_RESULT_TIMEOUT_SEC = 35.0
DEFAULT_PARAGRAPH_REST_PORTS = (5501, 5000)
PROBE_ISHD_REQUEST_TIMEOUT_SEC = 2.5
PROBE_ISHD_DOC_TIMEOUT_SEC = 6.0
PROBE_ISHD_ACTION_DIRECT_TIMEOUT_SEC = 1.0
PROBE_ISHD_ACTION_RESULT_TIMEOUT_SEC = 6.0
PROBE_REST_TIMEOUT_SEC = 3.0
PROBE_DB_CONNECT_TIMEOUT_SEC = 3.0


router = APIRouter(prefix="/targets", tags=["targets"])


class TargetUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    is_active: bool = False

    ishd_host: str = Field(min_length=1, max_length=255)
    ishd_port: int = 50200
    ishd_host_id: str = Field(min_length=1, max_length=255)
    ishd_software_name: str = Field(default="Paragraph Test System", min_length=1, max_length=255)
    ishd_login: Optional[str] = None
    ishd_password: Optional[str] = None
    ishd_target_host_id: str = "paragraf"
    ishd_target_host_ids: str = "paragraf"
    ishd_target_recipient: Optional[str] = None
    ishd_default_port: int = 8080
    ishd_request_timeout_sec: float = SAFE_ISHD_REQUEST_TIMEOUT_SEC
    ishd_doc_response_timeout_sec: float = SAFE_ISHD_DOC_RESPONSE_TIMEOUT_SEC
    ishd_action_direct_timeout_sec: float = SAFE_ISHD_ACTION_DIRECT_TIMEOUT_SEC
    ishd_action_result_timeout_sec: float = SAFE_ISHD_ACTION_RESULT_TIMEOUT_SEC

    paragraph_rest_base_url: Optional[str] = "http://127.0.0.1:5000"
    paragraph_db_dsn: Optional[str] = None


class TargetPatchRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    ishd_host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ishd_port: Optional[int] = None
    ishd_host_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ishd_software_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ishd_login: Optional[str] = None
    ishd_password: Optional[str] = None
    ishd_target_host_id: Optional[str] = None
    ishd_target_host_ids: Optional[str] = None
    ishd_target_recipient: Optional[str] = None
    ishd_default_port: Optional[int] = None
    ishd_request_timeout_sec: Optional[float] = None
    ishd_doc_response_timeout_sec: Optional[float] = None
    ishd_action_direct_timeout_sec: Optional[float] = None
    ishd_action_result_timeout_sec: Optional[float] = None

    paragraph_rest_base_url: Optional[str] = None
    paragraph_db_dsn: Optional[str] = None


class TargetAutoCurrentRequest(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Optional profile name. Default: auto-host-local or auto-vm-<ip>.",
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description for the profile.",
    )
    activate: bool = Field(
        default=True,
        description="Set detected profile active immediately.",
    )
    paragraph_rest_port: int = Field(
        default=5000,
        ge=1,
        le=65535,
        description="Preferred Paragraph REST port for auto-detection.",
    )
    ishd_host_override: Optional[str] = Field(
        default=None,
        description=(
            "Optional stand IP override for NAT case or manual routing. "
            "If set, used as ISHD host."
        ),
    )
    paragraph_rest_host_override: Optional[str] = Field(
        default=None,
        description=(
            "Optional stand IP override for Paragraph REST host. "
            "If not set, ISHD host value is used."
        ),
    )
    paragraph_db_dsn: Optional[str] = Field(
        default=None,
        description="Optional explicit Paragraph DB DSN. If omitted, backend tries to clone host from .env DSN.",
    )
    ishd_login: Optional[str] = Field(
        default=None,
        description=(
            "Optional ISHD login for this target profile. "
            "If omitted while updating, existing profile login is preserved."
        ),
    )
    ishd_password: Optional[str] = Field(
        default=None,
        description=(
            "Optional ISHD password for this target profile. "
            "If omitted while updating, existing profile password is preserved."
        ),
    )


def _serialize_target(target: TestTarget) -> dict:
    return {
        "id": target.id,
        "name": target.name,
        "description": target.description,
        "is_active": bool(target.is_active),
        "ishd": {
            "host": target.ishd_host,
            "port": target.ishd_port,
            "host_id": target.ishd_host_id,
            "software_name": target.ishd_software_name,
            "login": target.ishd_login,
            "password": target.ishd_password,
            "target_host_id": target.ishd_target_host_id,
            "target_host_ids": target.ishd_target_host_ids,
            "target_recipient": target.ishd_target_recipient,
            "default_port": target.ishd_default_port,
            "request_timeout_sec": target.ishd_request_timeout_sec,
            "doc_response_timeout_sec": target.ishd_doc_response_timeout_sec,
            "action_direct_timeout_sec": target.ishd_action_direct_timeout_sec,
            "action_result_timeout_sec": target.ishd_action_result_timeout_sec,
        },
        "paragraph_rest_base_url": target.paragraph_rest_base_url,
        "paragraph_db_dsn": target.paragraph_db_dsn,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "updated_at": target.updated_at.isoformat() if target.updated_at else None,
    }


def _extract_client_ip(request: Request) -> Optional[str]:
    # Dlya sebya: berem realnyy IP klienta (VM) dlya avto-registracii target.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip")
    if real:
        value = real.strip()
        if value:
            return value
    if request.client and request.client.host:
        return request.client.host
    return None


def _derive_db_dsn_for_host(client_ip: str) -> Optional[str]:
    # Dlya sebya: chtoby ne prosit kolleg vvodit DSN, berem .env DSN i menyaem host na IP VM.
    dsn = (settings.paragraph_db_dsn or "").strip()
    if not dsn:
        return None
    try:
        parsed = make_url(dsn)
        return str(parsed.set(host=client_ip))
    except Exception:
        return None


def _primary_host_id_from_csv(host_ids_csv: str) -> str:
    # Dlya sebya: v target hranim i primary, i csv-variant host_ids.
    parts = [item.strip() for item in str(host_ids_csv or "").split(",") if item.strip()]
    if parts:
        return parts[0]
    return "paragraf"


def _is_loopback_host(value: Optional[str]) -> bool:
    host = str(value or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost"}


def _unique_ints(values: tuple[int, ...] | list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for value in values:
        try:
            port = int(value)
        except Exception:
            continue
        if port <= 0 or port in seen:
            continue
        seen.add(port)
        out.append(port)
    return out


async def _tcp_probe(host: str, port: int, timeout_sec: float = 1.0) -> bool:
    # Dlya sebya: bystraya proverka porta, chtoby ne zhdat dolgie timeouty na nevernom REST URL.
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)),
            timeout=timeout_sec,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        del reader
        return True
    except Exception:
        return False


async def _detect_rest_base_url(host: str, preferred_port: int) -> str:
    # Dlya sebya: vybiraem ne prosto otkrytyy TCP-port, a real'no rabochiy REST endpoint.
    probe_ports = _unique_ints((preferred_port, *DEFAULT_PARAGRAPH_REST_PORTS))
    # Local host safe preference: worker REST usually on 5000.
    if _is_loopback_host(host) and 5000 in probe_ports:
        probe_ports = [5000] + [p for p in probe_ports if p != 5000]

    async def _rest_probe_ok(base_url: str) -> bool:
        try:
            raw = await asyncio.to_thread(
                paragraph_rest.list_dicts,
                base_url=base_url,
                timeout=int(PROBE_REST_TIMEOUT_SEC),
            )
            return isinstance(raw, list)
        except Exception:
            return False

    # 1) Prefer truly working REST base url.
    for port in probe_ports:
        candidate = f"http://{host}:{port}"
        if await _rest_probe_ok(candidate):
            return candidate

    # 2) Backward-compatible fallback: first reachable TCP port.
    for port in probe_ports:
        if await _tcp_probe(host, port):
            return f"http://{host}:{port}"

    return f"http://{host}:{int(preferred_port)}"


@router.get(
    "",
    summary="Список target-профилей",
    description="Профили VM/сборок для запуска тестов без правки .env.",
)
async def list_targets(session: AsyncSession = Depends(get_session)):
    # Dlya sebya: kolegam nuzhen spisok profiley, chtoby vybivat target iz UI.
    rows = await target_service.list_target_entities(session)
    default_target = target_service.default_runtime_target()
    return {
        "items": [
            {
                "id": None,
                "name": default_target.name,
                "description": default_target.description,
                "is_active": True,
                "is_default": True,
            },
            *[
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "is_active": bool(t.is_active),
                    "is_default": False,
                }
                for t in rows
            ],
        ]
    }


@router.get("/{target_id}", summary="Один target-профиль")
async def get_target(target_id: int, session: AsyncSession = Depends(get_session)):
    target = await target_service.get_target_entity(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return _serialize_target(target)


@router.post("", summary="Создать target-профиль")
async def create_target(payload: TargetUpsertRequest, session: AsyncSession = Depends(get_session)):
    existing = await session.execute(select(TestTarget).where(TestTarget.name == payload.name.strip()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Target with this name already exists")

    now = datetime.utcnow()
    entity = TestTarget(
        name=payload.name.strip(),
        description=payload.description,
        is_active=bool(payload.is_active),
        ishd_host=payload.ishd_host.strip(),
        ishd_port=payload.ishd_port,
        ishd_host_id=payload.ishd_host_id.strip(),
        ishd_software_name=payload.ishd_software_name.strip(),
        ishd_login=(payload.ishd_login or "").strip() or None,
        ishd_password=(payload.ishd_password or "").strip() or None,
        ishd_target_host_id=(payload.ishd_target_host_id or "paragraf").strip() or "paragraf",
        ishd_target_host_ids=(payload.ishd_target_host_ids or "paragraf").strip() or "paragraf",
        ishd_target_recipient=(payload.ishd_target_recipient or "").strip() or None,
        ishd_default_port=payload.ishd_default_port,
        ishd_request_timeout_sec=payload.ishd_request_timeout_sec,
        ishd_doc_response_timeout_sec=payload.ishd_doc_response_timeout_sec,
        ishd_action_direct_timeout_sec=payload.ishd_action_direct_timeout_sec,
        ishd_action_result_timeout_sec=payload.ishd_action_result_timeout_sec,
        paragraph_rest_base_url=(payload.paragraph_rest_base_url or "").strip() or None,
        paragraph_db_dsn=(payload.paragraph_db_dsn or "").strip() or None,
        created_at=now,
        updated_at=now,
    )

    if entity.is_active:
        await session.execute(TestTarget.__table__.update().values(is_active=False))

    session.add(entity)
    await session.commit()
    await session.refresh(entity)
    return _serialize_target(entity)


@router.patch("/{target_id}", summary="Обновить target-профиль")
async def update_target(
    target_id: int,
    payload: TargetPatchRequest,
    session: AsyncSession = Depends(get_session),
):
    target = await target_service.get_target_entity(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        value = str(data["name"]).strip()
        if not value:
            raise HTTPException(status_code=400, detail="name must not be empty")
        check = await session.execute(select(TestTarget).where(TestTarget.name == value, TestTarget.id != target_id))
        if check.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Target with this name already exists")
        target.name = value

    for field in (
        "description",
        "ishd_port",
        "ishd_default_port",
        "ishd_request_timeout_sec",
        "ishd_doc_response_timeout_sec",
        "ishd_action_direct_timeout_sec",
        "ishd_action_result_timeout_sec",
        "is_active",
    ):
        if field in data:
            setattr(target, field, data[field])

    for field in (
        "ishd_host",
        "ishd_host_id",
        "ishd_software_name",
        "ishd_login",
        "ishd_password",
        "ishd_target_host_id",
        "ishd_target_host_ids",
        "ishd_target_recipient",
        "paragraph_rest_base_url",
        "paragraph_db_dsn",
    ):
        if field in data:
            val = data[field]
            if isinstance(val, str):
                val = val.strip() or None
            setattr(target, field, val)

    if target.is_active:
        await session.execute(
            TestTarget.__table__.update().where(TestTarget.id != target.id).values(is_active=False)
        )

    target.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(target)
    return _serialize_target(target)


@router.post("/{target_id}/activate", summary="Сделать target активным")
async def set_target_active(target_id: int, session: AsyncSession = Depends(get_session)):
    entity = await target_service.activate_target(session, target_id)
    return _serialize_target(entity)


@router.delete("/{target_id}", summary="Удалить target-профиль")
async def delete_target(target_id: int, session: AsyncSession = Depends(get_session)):
    target = await target_service.get_target_entity(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    await session.delete(target)
    await session.commit()
    return {"status": "ok", "deleted_id": target_id}


@router.post(
    "/{target_id}/probe",
    summary="Проверка профиля target",
    description=(
        "Проверяет доступность ИШД, REST API Параграфа и подключения к БД "
        "для выбранного профиля."
    ),
)
async def probe_target(target_id: int, session: AsyncSession = Depends(get_session)):
    runtime_target = await target_service.resolve_runtime_target(session, target_id)
    out = {
        "target_id": runtime_target.id,
        "target_name": runtime_target.name,
        "ishd": {"ok": False, "message": ""},
        "paragraph_rest": {"ok": False, "message": ""},
        "paragraph_db": {"ok": False, "message": ""},
        "ok": False,
    }

    async def probe_ishd() -> None:
        # Fast readiness-check for UI button: shorter timeouts than production XML operations.
        probe_cfg = replace(
            runtime_target.ishd,
            request_timeout_sec=PROBE_ISHD_REQUEST_TIMEOUT_SEC,
            doc_response_timeout_sec=PROBE_ISHD_DOC_TIMEOUT_SEC,
            action_direct_timeout_sec=PROBE_ISHD_ACTION_DIRECT_TIMEOUT_SEC,
            action_result_timeout_sec=PROBE_ISHD_ACTION_RESULT_TIMEOUT_SEC,
        )
        ishd_client = IshdClient(config=probe_cfg)
        try:
            await ishd_client.connect()
            out["ishd"]["ok"] = True
            out["ishd"]["message"] = "connected"
        except Exception as e:
            out["ishd"]["message"] = str(e)
        finally:
            try:
                await ishd_client.disconnect()
            except Exception:
                pass

    async def probe_rest() -> None:
        rest_base = (runtime_target.paragraph_rest_base_url or "").strip()
        if not rest_base:
            out["paragraph_rest"]["message"] = "paragraph_rest_base_url is empty"
            return
        try:
            raw = await asyncio.to_thread(
                paragraph_rest.list_dicts,
                base_url=rest_base,
                timeout=int(PROBE_REST_TIMEOUT_SEC),
            )
            cnt = len(raw) if isinstance(raw, list) else "n/a"
            out["paragraph_rest"]["ok"] = True
            out["paragraph_rest"]["message"] = f"ok (dicts={cnt})"
        except ParagraphRestError as e:
            body = str(e.body or "")
            # Safe fallback for common local misconfig:
            # profile points to 5501, but Paragraph worker API is on 5000.
            fallback_base = _try_build_rest_fallback_to_5000(rest_base)
            should_try_fallback = (
                fallback_base is not None
                and int(getattr(e, "status", 0) or 0) == 404
                and "doesn't exist" in body.lower()
                and "/api/v1/meta/u_dict/" in body
            )
            if should_try_fallback:
                try:
                    raw_fb = await asyncio.to_thread(
                        paragraph_rest.list_dicts,
                        base_url=fallback_base,
                        timeout=int(PROBE_REST_TIMEOUT_SEC),
                    )
                    cnt_fb = len(raw_fb) if isinstance(raw_fb, list) else "n/a"
                    out["paragraph_rest"]["ok"] = True
                    out["paragraph_rest"]["message"] = (
                        f"ok (dicts={cnt_fb}); fallback applied configured={rest_base} -> effective={fallback_base}. "
                        "Profile should be updated to effective base_url."
                    )
                    return
                except ParagraphRestError as e_fb:
                    body_fb = f" body={e_fb.body}" if e_fb.body else ""
                    out["paragraph_rest"]["message"] = (
                        f"{e} body={body}; fallback {fallback_base} failed: {e_fb}{body_fb}"
                    )
                    return
                except Exception as e_fb:
                    out["paragraph_rest"]["message"] = (
                        f"{e} body={body}; fallback {fallback_base} failed: {e_fb}"
                    )
                    return
            body_suffix = f" body={body}" if body else ""
            out["paragraph_rest"]["message"] = f"{e}{body_suffix}"
        except Exception as e:
            out["paragraph_rest"]["message"] = str(e)

    async def probe_db() -> None:
        dsn = (runtime_target.paragraph_db_dsn or settings.paragraph_db_dsn or "").strip()
        if not dsn:
            out["paragraph_db"]["ok"] = True
            out["paragraph_db"]["message"] = "skipped (DSN is not configured)"
            return

        engine = create_async_engine(
            dsn,
            echo=False,
            pool_pre_ping=True,
            connect_args={"timeout": PROBE_DB_CONNECT_TIMEOUT_SEC},
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            out["paragraph_db"]["ok"] = True
            out["paragraph_db"]["message"] = "connected"
        except (SQLAlchemyError, OSError, Exception) as e:
            out["paragraph_db"]["message"] = str(e)
        finally:
            await engine.dispose()

    await asyncio.gather(
        probe_ishd(),
        probe_rest(),
        probe_db(),
    )

    out["ok"] = bool(out["ishd"]["ok"] and out["paragraph_rest"]["ok"] and out["paragraph_db"]["ok"])
    return out


def _try_build_rest_fallback_to_5000(rest_base: str) -> Optional[str]:
    # Dlya sebya: v probe bezopasno probuem fallback 5501 -> 5000 tol'ko dlya loopback.
    value = str(rest_base or "").strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = str(parsed.hostname or "").strip()
    if not _is_loopback_host(host):
        return None
    if int(parsed.port or 80) != 5501:
        return None
    fallback_netloc = f"{host}:5000"
    return urlunsplit((parsed.scheme, fallback_netloc, "", "", ""))


@router.post(
    "/auto/current",
    summary="Auto-configure current stand target",
    description=(
        "Creates or updates target based on where the UI is opened from: "
        "local host or virtual machine. "
        "Used to avoid manual IP and port setup."
    ),
)
async def auto_register_current_target(
    payload: TargetAutoCurrentRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    detected_ip = _extract_client_ip(request)
    if not detected_ip:
        raise HTTPException(status_code=400, detail="Cannot detect client IP")

    override_ishd_host = (payload.ishd_host_override or "").strip()
    override_rest_host = (payload.paragraph_rest_host_override or "").strip()
    preferred_rest_port = int(payload.paragraph_rest_port or DEFAULT_PARAGRAPH_REST_PORTS[0])

    if override_ishd_host and not _is_loopback_host(override_ishd_host):
        effective_ishd_host = override_ishd_host
        is_local_profile = False
        detected_from = f"manual stand IP {override_ishd_host}"
    elif _is_loopback_host(detected_ip):
        # Dlya sebya: esli UI otkryt na etom zhe PK, eto normalnyy lokalnyy stend.
        effective_ishd_host = "127.0.0.1"
        is_local_profile = True
        detected_from = "local host browser session"
    else:
        effective_ishd_host = detected_ip
        is_local_profile = False
        detected_from = f"client IP {detected_ip}"

    rest_host = (
        override_rest_host
        if override_rest_host and not _is_loopback_host(override_rest_host)
        else effective_ishd_host
    )
    rest_base_url = await _detect_rest_base_url(rest_host, preferred_rest_port)

    auto_name = payload.name.strip() if (payload.name or "").strip() else (
        "auto-host-local" if is_local_profile else f"auto-vm-{effective_ishd_host}"
    )
    auto_description = (
        payload.description.strip()
        if (payload.description or "").strip()
        else f"Auto detected from {detected_from}"
    )
    target_host_ids = (settings.ishd_target_host_ids or "paragraf").strip() or "paragraf"
    target_host_id = _primary_host_id_from_csv(target_host_ids)
    paragraph_db_dsn = (
        (payload.paragraph_db_dsn or "").strip()
        or (settings.paragraph_db_dsn if is_local_profile else _derive_db_dsn_for_host(rest_host))
    )
    payload_login = (payload.ishd_login or "").strip() or None
    payload_password = (payload.ishd_password or "").strip() or None
    safe_request_timeout = max(float(settings.ishd_request_timeout_sec), SAFE_ISHD_REQUEST_TIMEOUT_SEC)
    safe_doc_timeout = max(float(settings.ishd_doc_response_timeout_sec), SAFE_ISHD_DOC_RESPONSE_TIMEOUT_SEC)
    safe_action_direct_timeout = max(float(settings.ishd_action_direct_timeout_sec), SAFE_ISHD_ACTION_DIRECT_TIMEOUT_SEC)
    safe_action_result_timeout = max(float(settings.ishd_action_result_timeout_sec), SAFE_ISHD_ACTION_RESULT_TIMEOUT_SEC)

    existing_q = await session.execute(
        select(TestTarget).where(TestTarget.ishd_host == effective_ishd_host).order_by(TestTarget.id.desc())
    )
    entity = existing_q.scalars().first()
    unique_name = auto_name
    name_q = await session.execute(select(TestTarget).where(TestTarget.name == auto_name))
    by_name = name_q.scalar_one_or_none()
    if by_name is not None and (entity is None or by_name.id != entity.id):
        safe_ip = effective_ishd_host.replace(".", "_").replace(":", "_")
        unique_name = f"{auto_name}_{safe_ip}"

    if entity is None:
        entity = TestTarget(
            name=unique_name,
            description=auto_description,
            is_active=bool(payload.activate),
            ishd_host=effective_ishd_host,
            ishd_port=int(settings.ishd_port),
            ishd_host_id=settings.ishd_host_id,
            ishd_software_name=settings.ishd_software_name,
            ishd_login=payload_login,
            ishd_password=payload_password,
            ishd_target_host_id=target_host_id,
            ishd_target_host_ids=target_host_ids,
            ishd_target_recipient=settings.ishd_target_recipient,
            ishd_default_port=int(settings.ishd_default_port),
            ishd_request_timeout_sec=safe_request_timeout,
            ishd_doc_response_timeout_sec=safe_doc_timeout,
            ishd_action_direct_timeout_sec=safe_action_direct_timeout,
            ishd_action_result_timeout_sec=safe_action_result_timeout,
            paragraph_rest_base_url=rest_base_url,
            paragraph_db_dsn=paragraph_db_dsn,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(entity)
    else:
        entity.name = unique_name
        entity.description = auto_description
        entity.ishd_host = effective_ishd_host
        entity.ishd_port = int(settings.ishd_port)
        entity.ishd_host_id = settings.ishd_host_id
        entity.ishd_software_name = settings.ishd_software_name
        if payload_login is not None:
            entity.ishd_login = payload_login
        if payload_password is not None:
            entity.ishd_password = payload_password
        entity.ishd_target_host_id = target_host_id
        entity.ishd_target_host_ids = target_host_ids
        entity.ishd_target_recipient = settings.ishd_target_recipient
        entity.ishd_default_port = int(settings.ishd_default_port)
        entity.ishd_request_timeout_sec = safe_request_timeout
        entity.ishd_doc_response_timeout_sec = safe_doc_timeout
        entity.ishd_action_direct_timeout_sec = safe_action_direct_timeout
        entity.ishd_action_result_timeout_sec = safe_action_result_timeout
        entity.paragraph_rest_base_url = rest_base_url
        entity.paragraph_db_dsn = paragraph_db_dsn
        entity.is_active = bool(payload.activate)
        entity.updated_at = datetime.utcnow()

    if payload.activate:
        await session.execute(
            TestTarget.__table__.update().where(TestTarget.id != entity.id).values(is_active=False)
        )

    await session.commit()
    await session.refresh(entity)

    return {
        "status": "ok",
        "detected_client_ip": detected_ip,
        "effective_target_ip": effective_ishd_host,
        "is_local_profile": is_local_profile,
        "paragraph_rest_base_url": rest_base_url,
        "target": _serialize_target(entity),
    }
