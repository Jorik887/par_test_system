from typing import List, Optional, Any, Dict
from uuid import UUID
import os
import io
import json
import zipfile
import csv
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    Response,
)
from sqlalchemy import select, func, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from openpyxl import Workbook

from src.paragraph.db import get_paragraph_session
from src.paragraph import models as paragraph_models
from src.paragraph import schemas as paragraph_schemas


router = APIRouter(
    prefix="/paragraph",
    tags=["paragraph"],
)


def _safe_ascii_filename(raw_name: str, default: str) -> str:
    # Dlya sebya: vspomogatelnyy shag dlya API (safe ascii filename).
    name = (raw_name or "").strip().replace('"', "")
    if not name:
        name = default

    safe = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in name)
    if not safe:
        safe = default
    return safe


def _safe_zip_inner_name(raw_name: str, default: str) -> str:
    # Dlya sebya: vspomogatelnyy shag dlya API (safe zip inner name).
    base = os.path.basename(raw_name or "").strip()
    if not base:
        base = default

    base = base.replace("\\", "_").replace("/", "_")
    base = base.replace("..", "_")
    base = base.replace(":", "_")

    safe = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in base)
    return safe or default


def _dt_to_ms(dt: Optional[datetime]) -> Optional[int]:
    # Dlya sebya: vspomogatelnyy shag dlya API (dt to ms).
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _jsonable(value: Any) -> Any:
    # Dlya sebya: vspomogatelnyy shag dlya API (jsonable).
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _excel_cell_value(v: Any) -> Any:
    # Dlya sebya: vspomogatelnyy shag dlya API (excel cell value).
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    try:
        return json.dumps(_jsonable(v), ensure_ascii=False)
    except Exception:
        return str(v)


async def _get_files_for_result(
    session: AsyncSession,
    doc_id: UUID,
) -> List[Dict[str, Any]]:
    # Dlya sebya: vspomogatelnyy shag dlya API (get files for result).
    sql = text(
        """
        SELECT
            f.id              AS file_id,
            f.name            AS name,
            f.size            AS size,
            f.path            AS path,
            f.bytes           AS bytes_oid,
            f.in_file_system  AS in_file_system
        FROM documents.files AS f
        JOIN documents.files_document AS fd
            ON f.id = fd.id_file
        WHERE fd.id_result_document = :doc_id
        ORDER BY f."timestamp" DESC
        """
    )

    res = await session.execute(sql, {"doc_id": doc_id})
    rows = res.mappings().all()

    out: List[Dict[str, Any]] = []
    for r in rows:
        path = r.get("path")
        bytes_oid = r.get("bytes_oid")
        in_file_system = r.get("in_file_system")

        can_download = bool((path and in_file_system) or (bytes_oid is not None))
        reason = None
        if not can_download:
            reason = "Нет бинарника: path=NULL и bytes=NULL (или in_file_system=false)"

        out.append(
            {
                "file_id": str(r["file_id"]),
                "name": r.get("name"),
                "size": r.get("size"),
                "path": r.get("path"),
                "bytes_oid": r.get("bytes_oid"),
                "in_file_system": r.get("in_file_system"),
                "can_download": can_download,
                "reason": reason,
            }
        )
    return out


async def _download_file_bytes_like_paragraph(
    session: AsyncSession,
    file_id: UUID,
) -> tuple[bytes, str]:
    # Dlya sebya: vspomogatelnyy shag dlya API (download file bytes like paragraph).
    sql_meta = text(
        """
        SELECT
            name,
            path,
            size,
            bytes            AS bytes_oid,
            in_file_system
        FROM documents.files
        WHERE id = :file_id
        """
    )

    res = await session.execute(sql_meta, {"file_id": file_id})
    row = res.mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Файл не найден в documents.files",
        )

    name: Optional[str] = row["name"]
    path: Optional[str] = row["path"]
    bytes_oid: Optional[int] = row["bytes_oid"]
    in_file_system: Optional[bool] = row["in_file_system"]

    data: Optional[bytes] = None

    if path and in_file_system:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = None

    if data is None and bytes_oid is not None:
        sql_lo = text("SELECT lo_get(:oid) AS data")
        res_lo = await session.execute(sql_lo, {"oid": bytes_oid})
        row_lo = res_lo.mappings().first()
        if row_lo is not None and row_lo["data"] is not None:
            data = bytes(row_lo["data"])

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Бинарные данные файла не найдены (ни по path, ни в large object)",
        )

    filename_base = name or os.path.basename(path or "") or str(file_id)
    return data, filename_base


def _make_alias_like_paragraph(name: str) -> str:
    # Dlya sebya: vspomogatelnyy shag dlya API (make alias like paragraph).
    name = (name or "").strip()
    if not name:
        return "document"
    return name.replace(" ", "_")


def _clients_from_json_view(json_view: Any) -> List[Dict[str, Any]]:
    # Dlya sebya: vspomogatelnyy shag dlya API (clients from json view).
    clients: List[Dict[str, Any]] = []

    clients.append(
        {
            "hostId": "paragraf",
            "role": "executor",
            "softwareName": "",
            "userName": "",
            "userRank": "",
            "userRole": "",
        }
    )

    try:
        if isinstance(json_view, dict):
            meta = json_view.get("meta") or {}
            sender = meta.get("sender") or {}
            host = sender.get("host_name") or sender.get("hostId") or sender.get("host")
            soft = sender.get("soft_name") or sender.get("softwareName") or ""

            if host:
                clients.append(
                    {
                        "hostId": host,
                        "role": "author",
                        "softwareName": soft or "",
                        "userName": "",
                        "userRank": "",
                        "userRole": "",
                    }
                )
    except Exception:
        pass

    return clients


async def _build_paragraph_like_payload(
    session: AsyncSession,
    doc_id: UUID,
) -> Dict[str, Any]:
    # Dlya sebya: vspomogatelnyy shag dlya API (build paragraph like payload).
    rd = await session.get(paragraph_models.ResultDocument, doc_id)
    if rd is None:
        raise HTTPException(status_code=404, detail="Result document not found")

    doc = await session.get(paragraph_models.Document, rd.id_document) if rd.id_document else None

    alias = None
    if isinstance(rd.json_view, dict):
        alias = rd.json_view.get("alias")

    if not alias:
        alias = _make_alias_like_paragraph(rd.name or (doc.name if doc else "document"))

    clients = _clients_from_json_view(rd.json_view)

    date_ms = _dt_to_ms(rd.date_write) or _dt_to_ms(rd.date_create) or 0

    parametrs = rd.aggregated_params or {}

    doc_type = (doc.type if doc and doc.type else None) or "UNKNOWN"

    payload_item = {
        "alias": alias,
        "clients": clients,
        "date": date_ms,
        "parametrs": _jsonable(parametrs),
        "type": doc_type,
    }

    meta = {
        "id": str(rd.id),
        "name": rd.name,
        "id_document": str(rd.id_document) if rd.id_document else None,
        "date_create": rd.date_create.isoformat() if rd.date_create else None,
        "date_write": rd.date_write.isoformat() if rd.date_write else None,
    }

    files = await _get_files_for_result(session, doc_id)

    return {
        "payload": [payload_item],
        "meta": meta,
        "files": files,
    }


def _payload_to_csv_bytes(payload: List[Dict[str, Any]]) -> bytes:
    # Dlya sebya: vspomogatelnyy shag dlya API (payload to csv bytes).
    if not payload:
        return b""

    columns: List[str] = []
    for row in payload:
        for k in row.keys():
            if k not in columns:
                columns.append(k)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(columns)
    for row in payload:
        writer.writerow([_excel_cell_value(row.get(c)) for c in columns])

    return output.getvalue().encode("utf-8")


def _payload_to_xlsx_bytes(payload: List[Dict[str, Any]]) -> bytes:
    # Dlya sebya: vspomogatelnyy shag dlya API (payload to xlsx bytes).
    wb = Workbook()
    ws = wb.active
    ws.title = "document"

    if not payload:
        ws.append(["empty"])
    else:
        columns: List[str] = []
        for row in payload:
            for k in row.keys():
                if k not in columns:
                    columns.append(k)

        ws.append(columns)

        for row in payload:
            ws.append([_excel_cell_value(row.get(col)) for col in columns])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


async def _get_files_stats_for_results(
    session: AsyncSession,
    doc_ids: List[UUID],
) -> Dict[UUID, Dict[str, Any]]:
    # Dlya sebya: vspomogatelnyy shag dlya API (get files stats for results).
    if not doc_ids:
        return {}

    sql = text(
        """
        SELECT
            fd.id_result_document AS doc_id,
            COUNT(fd.id_file) AS files_linked_count,
            COUNT(fd.id_file) FILTER (
                WHERE ( (f.in_file_system = TRUE AND f.path IS NOT NULL) OR (f.bytes IS NOT NULL) )
            ) AS files_downloadable_count,
            COUNT(fd.id_file) FILTER (
                WHERE NOT ( (f.in_file_system = TRUE AND f.path IS NOT NULL) OR (f.bytes IS NOT NULL) )
            ) AS files_broken_count
        FROM documents.files_document fd
        JOIN documents.files f
            ON f.id = fd.id_file
        WHERE fd.id_result_document IN :doc_ids
        GROUP BY fd.id_result_document
        """
    ).bindparams(bindparam("doc_ids", expanding=True))

    res = await session.execute(sql, {"doc_ids": doc_ids})
    rows = res.mappings().all()

    out: Dict[UUID, Dict[str, Any]] = {}
    for r in rows:
        doc_id = r["doc_id"]
        linked = int(r["files_linked_count"] or 0)
        downloadable = int(r["files_downloadable_count"] or 0)
        broken = int(r["files_broken_count"] or 0)

        if linked <= 0:
            status_value = "no_files"
        elif downloadable <= 0:
            status_value = "all_broken"
        elif broken <= 0:
            status_value = "all_ok"
        else:
            status_value = "mixed"

        out[doc_id] = {
            "files_linked_count": linked,
            "files_downloadable_count": downloadable,
            "files_broken_count": broken,
            "files_status": status_value,
        }
    return out


@router.get(
    "/results",
    response_model=List[paragraph_schemas.ParagraphResultBrief],
    summary="Список результатных документов (result_document) с пагинацией",
)
async def list_results(
    offset: int = Query(0, ge=0, description="Смещение (для пагинации)"),
    limit: int = Query(50, ge=1, le=500, description="Количество записей на странице"),
    search: Optional[str] = Query(None, description="Поиск по имени (ILIKE)"),
    doc_type: Optional[str] = Query(None, description="Фильтр по типу документа (document.type)"),
    with_files: bool = Query(
        False,
        description="Если true — вернуть только документы, у которых есть связь с files_document",
    ),
    files_filter: Optional[str] = Query(
        None,
        description="Фильтр по файлам: all_ok | all_broken",
    ),
    session: AsyncSession = Depends(get_paragraph_session),
) -> List[paragraph_schemas.ParagraphResultBrief]:
    # Dlya sebya: endpoint "list_results" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    rd = paragraph_models.ResultDocument
    doc = paragraph_models.Document

    stmt = select(rd)

    if doc_type:
        stmt = stmt.join(doc, rd.id_document == doc.id).where(doc.type == doc_type)

    if search:
        stmt = stmt.where(rd.name.ilike(f"%{search}%"))

    if with_files:
        stmt = stmt.where(
            text(
                """
                EXISTS (
                    SELECT 1
                    FROM documents.files_document fd
                    JOIN documents.files f ON fd.id_file = f.id
                    WHERE fd.id_result_document = documents.result_document.id
                )
                """
            )
        )

    ff = (files_filter or "").strip().lower()
    if ff in {"all_ok", "all_broken"}:
        downloadable_exists = text(
            """
            EXISTS (
                SELECT 1
                FROM documents.files_document fd
                JOIN documents.files f ON fd.id_file = f.id
                WHERE fd.id_result_document = documents.result_document.id
                  AND ( (f.in_file_system = TRUE AND f.path IS NOT NULL) OR (f.bytes IS NOT NULL) )
            )
            """
        )
        broken_exists = text(
            """
            EXISTS (
                SELECT 1
                FROM documents.files_document fd
                JOIN documents.files f ON fd.id_file = f.id
                WHERE fd.id_result_document = documents.result_document.id
                  AND NOT ( (f.in_file_system = TRUE AND f.path IS NOT NULL) OR (f.bytes IS NOT NULL) )
            )
            """
        )
        any_files_exists = text(
            """
            EXISTS (
                SELECT 1
                FROM documents.files_document fd
                WHERE fd.id_result_document = documents.result_document.id
            )
            """
        )

        if ff == "all_ok":
            stmt = stmt.where(any_files_exists).where(downloadable_exists).where(text(f"NOT ({broken_exists.text})"))
        elif ff == "all_broken":
            stmt = stmt.where(any_files_exists).where(broken_exists).where(text(f"NOT ({downloadable_exists.text})"))

    stmt = (
        stmt.order_by(rd.date_write.desc().nullslast(), rd.date_create.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    items = result.scalars().all()

    doc_ids = [obj.id for obj in items]
    stats_map = await _get_files_stats_for_results(session, doc_ids)

    out: List[paragraph_schemas.ParagraphResultBrief] = []
    for obj in items:
        st = stats_map.get(obj.id)
        if st is None:
            obj.files_linked_count = 0
            obj.files_downloadable_count = 0
            obj.files_broken_count = 0
            obj.files_status = "no_files"
        else:
            obj.files_linked_count = st["files_linked_count"]
            obj.files_downloadable_count = st["files_downloadable_count"]
            obj.files_broken_count = st["files_broken_count"]
            obj.files_status = st["files_status"]

        out.append(paragraph_schemas.ParagraphResultBrief.from_attributes(obj))

    return out


@router.get(
    "/results/{result_id}",
    response_model=paragraph_schemas.ParagraphResultDocument,
    summary="Один результатный документ по id",
)
async def get_result(
    result_id: UUID,
    session: AsyncSession = Depends(get_paragraph_session),
) -> paragraph_schemas.ParagraphResultDocument:
    # Dlya sebya: endpoint "get_result" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    rd = paragraph_models.ResultDocument
    stmt = select(rd).where(rd.id == result_id)

    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()

    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result document not found")

    return paragraph_schemas.ParagraphResultDocument.from_attributes(entity)


@router.get(
    "/results/{doc_id}/content",
    response_model=paragraph_schemas.DocumentContent,
    summary="Сырой контент result_document_data",
)
async def get_result_content(
    doc_id: UUID,
    session: AsyncSession = Depends(get_paragraph_session),
) -> paragraph_schemas.DocumentContent:
    # Dlya sebya: endpoint "get_result_content" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    rd_data = await session.get(paragraph_models.ResultDocumentData, doc_id)
    if rd_data is None:
        raise HTTPException(status_code=404, detail="Содержимое не найдено")

    raw = rd_data.data or b""

    text_value: Optional[str] = None
    mime = "application/octet-stream"

    try:
        text_value = raw.decode("utf-8")
        stripped = text_value.lstrip()
        if stripped.startswith("<"):
            mime = "application/xml"
        elif stripped.startswith("{") or stripped.startswith("["):
            mime = "application/json"
        else:
            mime = "text/plain"
    except Exception:
        text_value = None

    return paragraph_schemas.DocumentContent(
        document_id=doc_id,
        mime=mime,
        size=len(raw),
        text=text_value,
    )


@router.get(
    "/results/{doc_id}/export-archive",
    summary="Экспорт документа в ZIP-архив (json + bin + файлы если есть)",
)
async def export_result_archive(
    doc_id: UUID,
    session: AsyncSession = Depends(get_paragraph_session),
):
    # Dlya sebya: endpoint "export_result_archive" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    rd = await session.get(paragraph_models.ResultDocument, doc_id)
    if rd is None:
        raise HTTPException(status_code=404, detail="Result document not found")

    rd_data = await session.get(paragraph_models.ResultDocumentData, doc_id)
    if rd_data is None:
        raise HTTPException(status_code=404, detail="result_document_data not found")

    raw_bin = rd_data.data or b""
    json_pack = await _build_paragraph_like_payload(session, doc_id)

    sql_files = text(
        """
        SELECT
            f.id AS file_id,
            f.name AS name
        FROM documents.files AS f
        JOIN documents.files_document AS fd
            ON f.id = fd.id_file
        WHERE fd.id_result_document = :doc_id
        ORDER BY f."timestamp" DESC
        """
    )
    res_files = await session.execute(sql_files, {"doc_id": doc_id})
    file_rows = res_files.mappings().all()

    safe_base = _safe_ascii_filename(str(rd.id), "result")
    zip_name = f"{safe_base}.zip"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "document.json",
            json.dumps(_jsonable(json_pack), ensure_ascii=False, indent=2).encode("utf-8"),
        )

        zf.writestr("document.bin", raw_bin)

        for fr in file_rows:
            file_id = fr["file_id"]
            raw_name = fr.get("name") or f"file_{file_id}"

            try:
                file_bytes, filename_base = await _download_file_bytes_like_paragraph(session, file_id)
            except HTTPException:
                continue

            inner_name = _safe_zip_inner_name(filename_base or raw_name, f"file_{file_id}")
            zf.writestr(f"files/{inner_name}", file_bytes)

    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.get(
    "/results/{doc_id}/export",
    summary="Экспорт документа в один из форматов (json/csv/excel)",
)
async def export_result(
    doc_id: UUID,
    format: str = Query("json", description="Формат: json | csv | excel"),
    session: AsyncSession = Depends(get_paragraph_session),
):
    # Dlya sebya: endpoint "export_result" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    format = (format or "").lower().strip()
    if format not in {"json", "csv", "excel"}:
        raise HTTPException(status_code=400, detail="format must be one of: json, csv, excel")

    pack = await _build_paragraph_like_payload(session, doc_id)
    payload = pack["payload"]

    safe_base = _safe_ascii_filename(str(doc_id), "result")

    if format == "json":
        filename = f"{safe_base}.json"
        content = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "csv":
        filename = f"{safe_base}.csv"
        content = _payload_to_csv_bytes(payload)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    filename = f"{safe_base}.xlsx"
    content = _payload_to_xlsx_bytes(payload)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
