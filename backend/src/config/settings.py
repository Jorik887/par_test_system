from typing import Optional
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Глобальные настройки приложения.
    Значения загружаются из .env в backend/.
    """

    # --- Основные настройки приложения ---
    app_name: str = "Paragraph Test Automation System"
    app_env: str = Field(default="dev", alias="APP_ENV")

    # --- БД (основная база системы тестирования) ---
    database_url: str = Field(alias="BACKEND_DB_DSN")

    # --- БД Paragraph (если когда-нибудь понадобится прямой доступ) ---
    paragraph_db_dsn: Optional[str] = Field(
        default=None,
        alias="PARAGRAPH_DB_DSN",
    )
    paragraph_rest_base_url: str = Field(
        default="http://127.0.0.1:5000",
        alias="PARAGRAPH_REST_BASE_URL",
    )
    paragraph_file_dirs: Optional[str] = Field(
        default=r"C:\documents_files",
        alias="PARAGRAPH_FILE_DIRS",
    )

    # --- Шифрование паролей ИШД ---
    crypto_key: Optional[str] = Field(default=None, alias="CRYPTO_KEY")

    # --- Настройки ИШД ---
    ishd_host: str = Field(alias="ISHD_HOST")
    ishd_port: int = Field(alias="ISHD_PORT")
    ishd_host_id: str = Field(alias="ISHD_HOST_ID")
    ishd_target_host_id: str = Field(default="paragraf", alias="ISHD_TARGET_HOST_ID")
    ishd_target_host_ids: str = Field(
        default="paragraf",
        alias="ISHD_TARGET_HOST_IDS",
    )
    ishd_target_recipient: Optional[str] = Field(default=None, alias="ISHD_TARGET_RECIPIENT")
    ishd_software_name: str = Field(alias="ISHD_SOFTWARE_NAME")
    ishd_default_port: int = Field(default=8080, alias="ISHD_DEFAULT_PORT")
    ishd_login: Optional[str] = Field(default=None, alias="ISHD_LOGIN")
    ishd_password: Optional[str] = Field(default=None, alias="ISHD_PASSWORD")
    ishd_request_timeout_sec: float = Field(
        default=8.0,
        alias="ISHD_REQUEST_TIMEOUT_SEC",
    )
    ishd_doc_response_timeout_sec: float = Field(
        default=35.0,
        alias="ISHD_DOC_RESPONSE_TIMEOUT_SEC",
    )
    ishd_action_direct_timeout_sec: float = Field(
        default=1.0,
        alias="ISHD_ACTION_DIRECT_TIMEOUT_SEC",
    )
    ishd_action_result_timeout_sec: float = Field(
        default=35.0,
        alias="ISHD_ACTION_RESULT_TIMEOUT_SEC",
    )

    # --- Конфиг модели ---
    _base_dir = Path(__file__).resolve().parents[2]
    model_config = SettingsConfigDict(
        env_file=_base_dir / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
