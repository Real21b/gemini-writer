"""
Configuration management for the Gemini Writer backend.
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # CORS
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    # AI Model
    model_name: str = Field(default="gemini-3-flash-preview", alias="MODEL_NAME")
    max_iterations: int = Field(default=300, alias="MAX_ITERATIONS")
    token_limit: int = Field(default=1_000_000, alias="TOKEN_LIMIT")
    compression_threshold: int = Field(default=900_000, alias="COMPRESSION_THRESHOLD")
    backup_interval: int = Field(default=50, alias="BACKUP_INTERVAL")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./gemini_writer.db",
        alias="DATABASE_URL",
    )

    # Output
    output_dir: str = Field(default="output", alias="OUTPUT_DIR")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
