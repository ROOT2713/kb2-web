"""
Application configuration via Pydantic Settings.

All configuration is loaded from environment variables or .env file.
No hardcoded values in business code.
"""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ──
    app_name: str = "kb-web"
    debug: bool = False

    # ── Server ──
    host: str = "0.0.0.0"
    port: int = 3002

    # ── Auth ──
    admin_username: str = "admin"
    admin_password: str = ""

    # ── CORS ──
    cors_origins: List[str] = ["*"]

    # ── Paths ──
    data_dir: Path = Path("./data")
    upload_dir: Path = Path("./data/uploads")
    db_path: Path = Path("./data/kb.db")
    banks_config_path: Path = Path("./data/banks.json")

    # ── Hindsight ──
    hindsight_url: str = "http://localhost:8080"

    # ── LLM ──
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_retries: int = 3
    llm_timeout: int = 60

    # ── Embedding ──
    embedding_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    # ── MinerU ──
    mineru_api_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    mineru_pages_max: int = 200

    # ── Cache ──
    cache_l1_max: int = 2000
    cache_l2_threshold: float = 0.82
    cache_ttl_seconds: int = 86400

    # ── Chunking ──
    default_chunk_size: int = 512
    chunk_overlap: int = 64

    # ── Retrieval ──
    top_k: int = 20
    rrf_k: int = 60

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()
