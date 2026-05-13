"""
config.py
Central settings loaded from .env — single source of truth for the whole app.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/classroom_companion"

    # LLM — swap provider without touching agent code
    LLM_PROVIDER: str = "anthropic"          # 'anthropic' | 'openai'
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL_ANTHROPIC: str = "claude-sonnet-4-20250514"
    LLM_MODEL_OPENAI: str = "gpt-4o"

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"


settings = Settings()
