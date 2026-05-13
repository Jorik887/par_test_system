from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from src.models.base import Base


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    test_case_run_id = Column(
        Integer,
        ForeignKey("test_case_runs.id"),
        nullable=False,
        index=True
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    level = Column(String(20), default="INFO", nullable=False)

    message = Column(Text, nullable=True)
    request_data = Column(Text, nullable=True)
    response_data = Column(Text, nullable=True)
    extra = Column(Text, nullable=True)

    case_run = relationship("TestCaseRun", back_populates="logs")
