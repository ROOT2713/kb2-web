"""Application configuration via Pydantic Settings.

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
    trust_proxy: bool = False  # 反代部署时置 True 才信任 X-Forwarded-For（2026-08-14 CC P1）

    # ── JWT ──
    jwt_secret: str = ""  # 【FIX-003】无默认密钥——空值启动即报错，杜绝默认密钥上线
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # ── CORS ──
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3027"]

    # ── Paths ──
    data_dir: Path = Path("./data")
    upload_dir: Path = Path("./data/uploads")
    db_path: Path = Path("./data/kb.db")
    banks_config_path: Path = Path("./data/banks.json")

    # ── Hindsight ──
    hindsight_url: str = "http://localhost:8080"

    # ── Vector Store ──
    vector_backend: str = "hindsight"  # "pgvector" | "hindsight" — 切换开关
    pgvector_database_url: str = ""  # 【FIX-003b】无默认口令——VECTOR_BACKEND=pgvector 时必须经 .env 显式提供

    # ── LLM ──
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_retries: int = 3
    llm_timeout: int = 60
    # 【R3-2】chat() 重试链总预算（秒）：≈ 网关/客户端超时(120s) 的 80%。
    # 最坏情形 3×60s+退避 ≈283s 会白烧配额且无人收货——总预算钳制在最坏耗时。
    chat_retry_budget_s: float = 96.0

    # ── Embedding ──
    embedding_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    # ── MinerU ──
    mineru_api_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    mineru_api_key2: str = ""
    mineru_pages_max: int = 200

    # ── Cache ──
    cache_l1_max: int = 2000
    cache_l2_threshold: float = 0.88
    cache_ttl_seconds: int = 86400

    # ── Chunking ──
    default_chunk_size: int = 500
    default_parent_size: int = 6000
    chunk_overlap: int = 75

    # ── Retrieval ──
    top_k: int = 20
    rrf_k: int = 60

    # ── Feature Flags (Phase 1 OKF) ──
    okf_domain_routing_enabled: bool = True     # 启用 domain 路由分流
    graphrag_enabled: bool = False               # GraphRAG 开关（Phase 2 决策门）

    # ── Confidence Rejection (Wave 0) ──
    confidence_reject_enabled: bool = True
    confidence_reject_threshold_l1: int = 0     # source_count=0 → 拒答
    confidence_reject_threshold_l2_coverage: float = 0.5
    confidence_reject_threshold_l3_validate: float = 0.25

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()

# 【FIX-003】JWT 密钥三重启动守卫：空值 / 残留默认值 / 弱长度均拒绝启动
if not settings.jwt_secret or "CHANGE_ME" in settings.jwt_secret:
    raise RuntimeError(
        "JWT_SECRET is empty or still the default 'CHANGE_ME_IN_PRODUCTION'. "
        "Set JWT_SECRET in .env before starting. Generate with: openssl rand -hex 32"
    )
if len(settings.jwt_secret) < 32:
    raise RuntimeError(
        "JWT_SECRET too short (< 32 chars) — weak secrets are brute-forceable. "
        "Generate with: openssl rand -hex 32"
    )

# 【FIX-003b】pgvector 后端必须显式配置连接串——禁止明文默认口令上线
if settings.vector_backend == "pgvector" and not settings.pgvector_database_url:
    raise RuntimeError(
        "VECTOR_BACKEND=pgvector 但未配置 pgvector_database_url. "
        "请在 .env 设置完整连接串 (postgresql://user:pass@host:port/db)"
    )