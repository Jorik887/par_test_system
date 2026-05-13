from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from src.models.base import Base


class TestTarget(Base):
    __test__ = False
    __tablename__ = "test_targets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, index=True)

    # ISHD connection profile for this target VM/build.
    ishd_host = Column(String(255), nullable=False)
    ishd_port = Column(Integer, nullable=False, default=50200)
    ishd_host_id = Column(String(255), nullable=False)
    ishd_software_name = Column(String(255), nullable=False)
    ishd_login = Column(String(255), nullable=True)
    ishd_password = Column(String(255), nullable=True)
    ishd_target_host_id = Column(String(255), nullable=False, default="paragraf")
    ishd_target_host_ids = Column(String(1024), nullable=False, default="paragraf")
    ishd_target_recipient = Column(String(255), nullable=True)
    ishd_default_port = Column(Integer, nullable=False, default=8080)
    ishd_request_timeout_sec = Column(Float, nullable=False, default=8.0)
    ishd_doc_response_timeout_sec = Column(Float, nullable=False, default=35.0)
    ishd_action_direct_timeout_sec = Column(Float, nullable=False, default=1.0)
    ishd_action_result_timeout_sec = Column(Float, nullable=False, default=35.0)

    # Paragraph-side connections for this target VM/build.
    paragraph_rest_base_url = Column(String(255), nullable=True)
    paragraph_db_dsn = Column(String(1024), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = {"extend_existing": True}
