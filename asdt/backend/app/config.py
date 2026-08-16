from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./asdt.db"
    atdt_base_url: str = "http://localhost:8000"
    gap_threshold: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
