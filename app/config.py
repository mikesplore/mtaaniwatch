from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "MtaaniWatch API"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://mike@localhost:5432/mtaaniwatchdb"
    database_password: str | None = None
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_stt_model: str = "whisper-large-v3-turbo"
    at_public_base_url: str | None = None
    at_username: str = "sandbox"
    at_api_key: str | None = None
    at_sender_id: str | None = None
    at_shortcode: str | None = None
    at_webhook_token: str | None = None
    at_sms_polling_enabled: bool = False
    at_sms_poll_interval: float = 20.0

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    @property
    def sqlalchemy_database_url(self) -> URL:
        url = make_url(self.database_url)
        if self.database_password is not None:
            url = url.set(password=self.database_password)
        return url


settings = Settings()
