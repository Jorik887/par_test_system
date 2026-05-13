from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: Any):
        # Dlya sebya: shag Paragraph-sloya (from attributes).
        return cls.model_validate(obj)


class ParagraphResultBrief(ORMBase):
    id: UUID
    name: Optional[str] = None
    date_create: Optional[datetime] = None
    date_write: Optional[datetime] = None

    id_document: Optional[UUID] = None
    ai_id: Optional[UUID] = None

    batch: Optional[str] = None
    number: Optional[int] = None

    important: Optional[bool] = None
    sender: Optional[str] = None
    receivers: Optional[str] = None
    taskid: Optional[str] = None

    comments_count: Optional[int] = None
    files_count: Optional[int] = None
    tags_count: Optional[int] = None

    files_linked_count: Optional[int] = None
    files_downloadable_count: Optional[int] = None
    files_broken_count: Optional[int] = None
    files_status: Optional[str] = None


class ParagraphResultDocument(ParagraphResultBrief):
    viewed: Optional[Dict[str, Any]] = None
    checked: Optional[Dict[str, Any]] = None

    aggregated_params: Optional[Dict[str, Any]] = None
    isbad: Optional[bool] = None
    errors: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    json_view: Optional[Dict[str, Any]] = None


class ParagraphDocumentBrief(ORMBase):
    id: UUID
    name: Optional[str] = None
    date_create: Optional[datetime] = None
    type: Optional[str] = None

    enabled: Optional[bool] = None
    section: Optional[int] = None

    enabled_files: Optional[bool] = None
    not_empty: Optional[bool] = None
    not_deleted: Optional[bool] = None

    estimate: Optional[int] = None


class ParagraphDocument(ParagraphDocumentBrief):
    data: Optional[str] = None


class DocumentContent(BaseModel):
    document_id: UUID
    mime: str
    size: int
    text: Optional[str] = None


class FileInfo(BaseModel):
    file_id: UUID
    name: Optional[str] = None
    size: Optional[int] = None
