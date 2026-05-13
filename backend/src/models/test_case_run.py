from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship
from src.models.base import Base

class TestCaseRun(Base):
    __test__ = False
    __tablename__ = 'test_case_runs'
    id = Column(Integer, primary_key=True, index=True)
    test_case_id = Column(Integer, ForeignKey('test_cases.id'))
    status = Column(String)

    test_case = relationship("TestCase", back_populates="runs")
    logs = relationship("LogEntry", back_populates="case_run")

    __table_args__ = {'extend_existing': True} 
