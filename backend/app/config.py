from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./atdt.db"

    jwt_secret: str = "change-me-dev-only-not-secure"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    chroma_dir: str = "./chroma_data"
    openai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
