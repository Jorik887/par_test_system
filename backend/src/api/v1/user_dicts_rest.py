import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import get_session
from src.services import paragraph_rest
from src.services.targets import resolve_runtime_target, resolve_target_id_from_request


router = APIRouter(prefix="/dicts-rest", tags=["user-dicts-rest"])


class RestColumn(BaseModel):
    name: str
    type: int = Field(1, description="Type code from API.pdf (TEXT=1, INT=2, BOOL=5, etc.)")
    note: str = "text"
    not_null: bool = True
    mask: bool = False
    interpretation: int = 3


class RestCreateRequest(BaseModel):
    name: str
    columns: Optional[List[RestColumn]] = None
    visible: int = 0
    type: int = 0


class RestDeleteRequest(BaseModel):
    table_uid: str
    delete_cascade: bool = False


async def _resolve_rest_base_url(request: Request, session: AsyncSession) -> Optional[str]:
    target_id = resolve_target_id_from_request(request)
    runtime_target = await resolve_runtime_target(session, target_id)
    return runtime_target.paragraph_rest_base_url


async def _run_rest(func, *args, **kwargs):
    # Dlya sebya: paragraph_rest sdelan sync (urllib), v async endpointah uводim ego v thread.
    return await asyncio.to_thread(func, *args, **kwargs)


@router.get("/list")
async def list_dicts(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "list_dicts" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.list_dicts,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.post("/create")
async def create_dict(
    payload: RestCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "create_dict" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        cols = [c.model_dump() for c in payload.columns] if payload.columns else None
        return await _run_rest(
            paragraph_rest.create_dict,
            payload.name,
            columns=cols,
            visible=payload.visible,
            dict_type=payload.type,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.get("/meta/{table_uid}")
async def get_meta(
    table_uid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "get_meta" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.get_meta,
            table_uid,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.delete("/delete/{table_uid}")
async def delete_dict(
    table_uid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    delete_cascade: bool = False,
):
    # Dlya sebya: endpoint "delete_dict" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.delete_dict,
            table_uid,
            delete_cascade=delete_cascade,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.post("/rows/{table_uid}")
async def insert_rows(
    table_uid: str,
    rows: List[Dict[str, Any]],
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "insert_rows" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.insert_rows,
            table_uid,
            rows,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.get("/rows/{table_uid}")
async def get_rows(
    table_uid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "get_rows" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.get_rows,
            table_uid,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})


@router.put("/rows/{table_uid}/{row_id}")
async def update_row(
    table_uid: str,
    row_id: str,
    values: Dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # Dlya sebya: endpoint "update_row" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        return await _run_rest(
            paragraph_rest.update_row,
            table_uid,
            row_id,
            values,
            base_url=await _resolve_rest_base_url(request, session),
        )
    except paragraph_rest.ParagraphRestError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "status": e.status, "body": e.body})
