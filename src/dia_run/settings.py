from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    use_mock_data: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = AppSettings()
