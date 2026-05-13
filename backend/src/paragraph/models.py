from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    Text,
    LargeBinary,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.paragraph.db import Base

# Таблица document

class Document(Base):
    """
    Шаблон документа (таблица documents.document).
    """

    __tablename__ = "document"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    date_create: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    section: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled_files: Mapped[bool] = mapped_column(Boolean, nullable=False)
    not_empty: Mapped[bool] = mapped_column(Boolean, nullable=False)
    not_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    estimate: Mapped[int] = mapped_column(Integer, nullable=False)

    # связь с результатными документами
    results: Mapped[list["ResultDocument"]] = relationship(
        back_populates="document",
        lazy="selectin",
    )

# Таблица result_document

class ResultDocument(Base):
    """
    Результатный документ (таблица documents.result_document).
    """

    __tablename__ = "result_document"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    date_create: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_write: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    id_document: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document.id"),
        nullable=False,
    )

    ai_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )

    batch: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    important: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    sender: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    receivers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    taskid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    viewed: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checked: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    comments_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    aggregated_params: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    isbad: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    errors: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    parent_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    json_view: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # связь обратно к шаблону документа
    document: Mapped["Document"] = relationship(
        back_populates="results",
        lazy="joined",
    )

    # связь с бинарными данными
    data_row: Mapped[Optional["ResultDocumentData"]] = relationship(
        back_populates="result_document",
        uselist=False,
        lazy="selectin",
    )

# Таблица result_document_data

class ResultDocumentData(Base):
    """
    Сырая бинарная нагрузка результатного документа (таблица documents.result_document_data).
    """

    __tablename__ = "result_document_data"
    __table_args__ = {"schema": "documents"}

    id_result_document: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.result_document.id"),
        primary_key=True,
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    result_document: Mapped["ResultDocument"] = relationship(
        back_populates="data_row",
        lazy="joined",
    )

# Таблица parametrs (параметры документа)

class Parametr(Base):
    """
    Таблица documents.parametrs — описание параметров документа (имя, alias, тип и т.п.).
    """

    __tablename__ = "parametrs"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    id_document: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    id_parent: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )

    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ltree в БД — храним как текст
    path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    text_view: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_secondary: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

# Таблица result_parametr (значения параметров)

class ResultParametr(Base):
    """
    Таблица documents.result_parametr — значения параметров для конкретного result_document.
    """

    __tablename__ = "result_parametr"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    id_parametr: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.parametrs.id"),
        nullable=False,
    )
    id_result_document: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.result_document.id"),
        nullable=False,
    )

    # В БД это "order" ARRAY — допустим, массив int
    order: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(Integer),
        nullable=True,
    )
    text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

# Таблица user_doccolumns (пользовательские настройки колонок)

class UserDocColumns(Base):
    """
    Таблица documents.user_doccolumns — пользовательские настройки отображения колонок.
    """

    __tablename__ = "user_doccolumns"
    __table_args__ = {"schema": "documents"}

    uid: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    fields: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    id_user: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

# Таблица files (файлы, бинарь хранится в large object через поле bytes)

class Files(Base):
    """
    Таблица documents.files.

    name, size  — метаданные файла,
    bytes       — OID large object (pg_largeobject),
    path        — путь на ФС (обычно NULL, когда файл хранится в БД).
    """

    __tablename__ = "files"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )

    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # колонка bytes INTEGER, но называем поле bytes_oid, чтобы не путать с type bytes
    bytes_oid: Mapped[Optional[int]] = mapped_column("bytes", Integer, nullable=True)

# Таблица files_document (связка result_document ↔ files)

class FilesDocument(Base):
    """
    Таблица documents.files_document.

    В реальной БД всего два поля:
      id_result_document UUID
      id_file            UUID

    Для чтения мы используем raw SQL, поэтому модель почти не трогаем.
    """

    __tablename__ = "files_document"
    __table_args__ = {"schema": "documents"}

    id_result_document: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    id_file: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
