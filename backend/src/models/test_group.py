from sqlalchemy import Column, Integer, String
from src.models.base import Base

class TestGroup(Base):
    __test__ = False
    __tablename__ = 'test_groups'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)

    __table_args__ = {'extend_existing': True}
