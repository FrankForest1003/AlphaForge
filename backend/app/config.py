from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    worker_base_url: str
    worker_token: str
    universe_path: Path
    lean_docs_path: Path
    api_key: str
    base_url: str
    model: str
    thinking_enabled: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def load_settings() -> Settings:
    return Settings(
        worker_base_url=os.getenv(
            "ALPHAFORGE_WORKER_URL", "http://127.0.0.1:18081"
        ).rstrip("/"),
        worker_token=os.getenv("ALPHAFORGE_WORKER_TOKEN", ""),
        universe_path=Path(
            os.getenv(
                "ALPHAFORGE_UNIVERSE_CONFIG",
                REPOSITORY_ROOT
                / "lean_worker"
                / "config"
                / "universe_whitelist_v1.0.json",
            )
        ).resolve(),
        lean_docs_path=Path(
            os.getenv(
                "ALPHAFORGE_LEAN_DOCS_PATH",
                REPOSITORY_ROOT / "docs" / "lean" / "text" / "alphaforge-python-v1",
            )
        ).resolve(),
        api_key=os.getenv("API_KEY", "").strip(),
        base_url=os.getenv("BASE_URL", "https://api.deepseek.com").rstrip("/"),
        model=os.getenv("MODEL", "deepseek-v4-pro").strip(),
        thinking_enabled=_env_bool("THINKING_ENABLED", True),
    )
