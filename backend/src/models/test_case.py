from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from src.models.base import Base


class TestCase(Base):
    __test__ = False
    __tablename__ = 'test_cases'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    runs = relationship("TestCaseRun", back_populates="test_case")

    __table_args__ = {'extend_existing': True}
