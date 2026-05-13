from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class DocumentBase(BaseModel):
    name: str
    type: Optional[str] = None
    enabled: bool
    section: int

class DocumentCreate(DocumentBase):
    pass

class DocumentUpdate(DocumentBase):
    pass

class DocumentInDB(DocumentBase):
    id: UUID
    date_create: datetime

    class Config:
        orm_mode = True
