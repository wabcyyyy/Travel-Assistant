import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str) -> str:
    return os.getenv(name, default)


class Settings:
    llm_base_url: str = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = _get("LLM_API_KEY", "")
    llm_model: str = _get("LLM_MODEL", "qwen-plus")
    llm_timeout: float = float(_get("LLM_TIMEOUT", "60"))
    agent_internal_token: str = _get("AGENT_INTERNAL_TOKEN", "")
    live_price_search: bool = _get("LIVE_PRICE_SEARCH", "true").lower() in ("1", "true", "yes")
    max_live_queries: int = int(_get("MAX_LIVE_QUERIES", "3"))
    default_budget: float = float(_get("DEFAULT_BUDGET", "1000"))
    db_host: str = _get("DB_HOST", "localhost")
    db_port: int = int(_get("DB_PORT", "3306"))
    db_user: str = _get("DB_USER", "root")
    db_password: str = _get("DB_PASSWORD", "root")
    db_name: str = _get("DB_NAME", "travel_assistant")


settings = Settings()
