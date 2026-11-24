"""Application configuration loaded from environment variables."""

import os
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

# Prevent litellm from fetching remote cost map in offline/container environments
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


class Settings:
    """Settings loaded strictly from environment variables."""

    def __init__(self):
        # Model config
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash-lite").strip()

        # Database URL
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db").strip()

        # Allowed CORS origins
        allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,*")
        self.ALLOWED_ORIGINS: List[str] = [
            origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()
        ]

        # Failure simulation hook switch
        simulation_raw = os.getenv("ENABLE_FAILURE_SIMULATION", "true").strip().lower()
        self.ENABLE_FAILURE_SIMULATION: bool = simulation_raw in ("true", "1", "yes")

        # Default system prompt
        self.DEFAULT_SYSTEM_PROMPT: str = os.getenv(
            "DEFAULT_SYSTEM_PROMPT",
            "You are Relay, an intelligent, helpful, and transparent AI assistant.",
        ).strip()

        # Key pool: parsed into ordered list of tuples: [("key_1", "raw_key_secret"), ...]
        raw_keys = os.getenv("LLM_API_KEYS", "")
        keys_list = [k.strip() for k in raw_keys.split(",") if k.strip()]
        self.KEY_POOL: List[Tuple[str, str]] = [
            (f"key_{idx + 1}", key) for idx, key in enumerate(keys_list)
        ]

    def reload(self):
        """Reload settings if environment changes (useful in testing)."""
        self.__init__()

    @property
    def sqlite_path(self) -> str:
        """Extract filesystem path from DATABASE_URL."""
        url = self.DATABASE_URL
        if url.startswith("sqlite:////"):
            return "/" + url[len("sqlite:////") :]
        elif url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        elif url.startswith("sqlite://"):
            return url[len("sqlite://") :]
        return url


settings = Settings()
