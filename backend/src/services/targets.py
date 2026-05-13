from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.test_target import TestTarget

MIN_ISHD_REQUEST_TIMEOUT_SEC = 8.0
MIN_ISHD_DOC_RESPONSE_TIMEOUT_SEC = 35.0
MIN_ISHD_ACTION_DIRECT_TIMEOUT_SEC = 1.0
MIN_ISHD_ACTION_RESULT_TIMEOUT_SEC = 35.0


@dataclass(slots=True)
class IshdConnectionConfig:
    host: str
    port: int
    host_id: str
    software_name: str
    target_host_id: str
    target_host_ids: str
    target_recipient: Optional[str]
    default_port: int
    login: Optional[str]
    password: Optional[str]
    request_timeout_sec: float
    doc_response_timeout_sec: float
    action_direct_timeout_sec: float
    action_result_timeout_sec: float


@dataclass(slots=True)
class RuntimeTarget:
    id: Optional[int]
    name: str
    description: Optional[str]
    is_active: bool
    is_default: bool
    ishd: IshdConnectionConfig
    paragraph_rest_base_url: Optional[str]
    paragraph_db_dsn: Optional[str]


def _normalize_ishd_timeouts(cfg: IshdConnectionConfig) -> IshdConnectionConfig:
    # Dlya sebya: na medlennykh sborkakh Paragraph final action mozhet idti 20+ sec.
    # Zashchita ot lozhnyh timeoutov: runtime nikogda ne opuskayem nizhye bezopasnogo minimuma.
    return IshdConnectionConfig(
        host=cfg.host,
        port=cfg.port,
        host_id=cfg.host_id,
        software_name=cfg.software_name,
        target_host_id=cfg.target_host_id,
        target_host_ids=cfg.target_host_ids,
        target_recipient=cfg.target_recipient,
        default_port=cfg.default_port,
        login=cfg.login,
        password=cfg.password,
        request_timeout_sec=max(float(cfg.request_timeout_sec), MIN_ISHD_REQUEST_TIMEOUT_SEC),
        doc_response_timeout_sec=max(float(cfg.doc_response_timeout_sec), MIN_ISHD_DOC_RESPONSE_TIMEOUT_SEC),
        action_direct_timeout_sec=max(float(cfg.action_direct_timeout_sec), MIN_ISHD_ACTION_DIRECT_TIMEOUT_SEC),
        action_result_timeout_sec=max(float(cfg.action_result_timeout_sec), MIN_ISHD_ACTION_RESULT_TIMEOUT_SEC),
    )


def _to_runtime_target(entity: TestTarget) -> RuntimeTarget:
    runtime = RuntimeTarget(
        id=entity.id,
        name=entity.name,
        description=entity.description,
        is_active=bool(entity.is_active),
        is_default=False,
        ishd=IshdConnectionConfig(
            host=entity.ishd_host,
            port=int(entity.ishd_port),
            host_id=entity.ishd_host_id,
            software_name=entity.ishd_software_name,
            target_host_id=entity.ishd_target_host_id,
            target_host_ids=entity.ishd_target_host_ids,
            target_recipient=entity.ishd_target_recipient,
            default_port=int(entity.ishd_default_port),
            login=entity.ishd_login,
            password=entity.ishd_password,
            request_timeout_sec=float(entity.ishd_request_timeout_sec),
            doc_response_timeout_sec=float(entity.ishd_doc_response_timeout_sec),
            action_direct_timeout_sec=float(entity.ishd_action_direct_timeout_sec),
            action_result_timeout_sec=float(entity.ishd_action_result_timeout_sec),
        ),
        paragraph_rest_base_url=entity.paragraph_rest_base_url,
        paragraph_db_dsn=entity.paragraph_db_dsn,
    )
    runtime.ishd = _normalize_ishd_timeouts(runtime.ishd)
    return runtime


def default_runtime_target() -> RuntimeTarget:
    runtime = RuntimeTarget(
        id=None,
        name="env-default",
        description="Default target from backend .env",
        is_active=True,
        is_default=True,
        ishd=IshdConnectionConfig(
            host=settings.ishd_host,
            port=int(settings.ishd_port),
            host_id=settings.ishd_host_id,
            software_name=settings.ishd_software_name,
            target_host_id=settings.ishd_target_host_id,
            target_host_ids=settings.ishd_target_host_ids,
            target_recipient=settings.ishd_target_recipient,
            default_port=int(settings.ishd_default_port),
            login=settings.ishd_login,
            password=settings.ishd_password,
            request_timeout_sec=float(settings.ishd_request_timeout_sec),
            doc_response_timeout_sec=float(settings.ishd_doc_response_timeout_sec),
            action_direct_timeout_sec=float(settings.ishd_action_direct_timeout_sec),
            action_result_timeout_sec=float(settings.ishd_action_result_timeout_sec),
        ),
        paragraph_rest_base_url=settings.paragraph_rest_base_url,
        paragraph_db_dsn=settings.paragraph_db_dsn,
    )
    runtime.ishd = _normalize_ishd_timeouts(runtime.ishd)
    return runtime


def resolve_target_id_from_request(request: Request) -> Optional[int]:
    # Dlya sebya: target mozhno peredat query `target_id` ili header `X-Target-ID`.
    raw = request.query_params.get("target_id")
    if raw is None:
        raw = request.headers.get("X-Target-ID")
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="target_id must be integer") from e


async def get_target_entity(session: AsyncSession, target_id: int) -> Optional[TestTarget]:
    result = await session.execute(select(TestTarget).where(TestTarget.id == target_id))
    return result.scalar_one_or_none()


async def list_target_entities(session: AsyncSession) -> list[TestTarget]:
    result = await session.execute(select(TestTarget).order_by(TestTarget.name.asc()))
    return list(result.scalars().all())


async def activate_target(session: AsyncSession, target_id: int) -> TestTarget:
    target = await get_target_entity(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    await session.execute(update(TestTarget).values(is_active=False))
    target.is_active = True
    await session.commit()
    await session.refresh(target)
    return target


async def get_active_target(session: AsyncSession) -> Optional[TestTarget]:
    result = await session.execute(
        select(TestTarget).where(TestTarget.is_active.is_(True)).order_by(TestTarget.id.desc())
    )
    return result.scalars().first()


async def resolve_runtime_target(
    session: AsyncSession,
    target_id: Optional[int],
) -> RuntimeTarget:
    if target_id is None:
        return default_runtime_target()

    target = await get_target_entity(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return _to_runtime_target(target)
