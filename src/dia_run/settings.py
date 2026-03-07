from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    app_env: Literal["development", "production"] = "development"
    use_mock_data: bool = False
    data_root: Path = Path("data")
    carelink_token_file: Path = Path("logindata.json")
    strava_refresh_token_file: Path | None = None
    s3_sync_enabled: bool = False
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_sync_on_startup: bool = False
    s3_sync_after_fetch: bool = False
    s3_sync_after_questionnaire: bool = False
    aws_region: str | None = None

    @field_validator("s3_prefix")
    @classmethod
    def normalize_s3_prefix(cls, value: str) -> str:
        return value.strip("/")

    @field_validator("strava_refresh_token_file", mode="before")
    @classmethod
    def normalize_refresh_token_file(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = AppSettings()
