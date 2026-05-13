from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import get_session
from src.ishd.client import IshdClient
from src.ishd.deps import get_ishd_client
from src.services.targets import resolve_runtime_target, resolve_target_id_from_request


async def get_ishd_client_for_request(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: odin dependency dlya multi-target ISHD vo vseh routerah.
    target_id = resolve_target_id_from_request(request)
    if target_id is None:
        try:
            yield get_ishd_client()
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Default ISHD client is not initialized. "
                    "Pass target_id or configure reachable .env ISHD."
                ),
            ) from e
        return

    runtime_target = await resolve_runtime_target(session, target_id)
    client = IshdClient(config=runtime_target.ishd)
    try:
        await client.connect()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect ISHD target {runtime_target.name}: {e}",
        ) from e

    try:
        yield client
    finally:
        await client.disconnect()

