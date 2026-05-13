from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from src.models.base import Base

class TestRunLog(Base):
    __test__ = False
    __tablename__ = 'test_run_logs'
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey('test_runs.id'), nullable=False, index=True)
    step_number = Column(Integer, nullable=False, default=0)
    request = Column(Text, nullable=True)
    response = Column(Text, nullable=True)
    status = Column(String(20), nullable=False)
    message = Column(String(255), nullable=True)

    test_run = relationship("TestRun", back_populates="logs")

    __table_args__ = {'extend_existing': True}
