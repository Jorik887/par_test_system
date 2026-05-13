from typing import Optional
from src.ishd.client import IshdClient  # Исправленный импорт
from src.paragraph.xml_templates import generate_create_user_dict_v1, generate_remove_user_dict, generate_query_user_dict
from src.paragraph.db import AsyncSessionLocal
from src.paragraph.models import Document, ResultDocument, Parametr, ResultParametr, ResultDocumentData
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

class ParagraphRepository:
    def __init__(self, session_factory=AsyncSessionLocal) -> None:
        # Dlya sebya: shag Paragraph-sloya (init).
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        # Dlya sebya: shag Paragraph-sloya (session).
        return self._session_factory()

    async def list_documents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        doc_type: Optional[str] = None,
        name_ilike: Optional[str] = None,
    ) -> list[Document]:
        # Dlya sebya: shag Paragraph-sloya (list documents).
        async with self._session() as session:
            stmt = select(Document).order_by(Document.date_create.desc())

            if doc_type is not None:
                stmt = stmt.where(Document.type == doc_type)

            if name_ilike:
                stmt = stmt.where(Document.name.ilike(f"%{name_ilike}%"))

            stmt = stmt.limit(limit).offset(offset)
            result = await session.scalars(stmt)
            return list(result)

    async def create_user_dict_v1(self) -> dict:
        # Dlya sebya: shag Paragraph-sloya (create user dict v1).
        xml_text = generate_create_user_dict_v1()
        ishd_client = IshdClient()
        try:
            response = await ishd_client.send_xml_over_ishd(xml_text)
            if response['status'] != 'ok':
                return {"status": "fail", "message": "Failed to create user dictionary"}
            return {"status": "ok", "message": "User dictionary created successfully"}
        except Exception as e:
            return {"status": "fail", "message": str(e)}

    async def remove_user_dict(self) -> dict:
        # Dlya sebya: shag Paragraph-sloya (remove user dict).
        xml_text = generate_remove_user_dict()
        ishd_client = IshdClient()
        try:
            response = await ishd_client.send_xml_over_ishd(xml_text)
            if response['status'] != 'ok':
                return {"status": "fail", "message": "Failed to remove user dictionary"}
            return {"status": "ok", "message": "User dictionary removed successfully"}
        except Exception as e:
            return {"status": "fail", "message": str(e)}

    async def query_user_dict(self) -> dict:
        # Dlya sebya: shag Paragraph-sloya (query user dict).
        xml_text = generate_query_user_dict()
        ishd_client = IshdClient()
        try:
            response = await ishd_client.send_xml_over_ishd(xml_text)
            if response['status'] != 'ok':
                return {"status": "fail", "message": "Failed to query user dictionary"}
            return {"status": "ok", "data": response['data']}
        except Exception as e:
            return {"status": "fail", "message": str(e)}
