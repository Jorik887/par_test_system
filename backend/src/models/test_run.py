from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.constants.enums import TestStatus

class TestRun(Base):
    __test__ = False
    __tablename__ = 'test_runs'
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default=TestStatus.PENDING.value, nullable=False)

    logs = relationship("TestRunLog", back_populates="test_run")

    __table_args__ = {'extend_existing': True}
