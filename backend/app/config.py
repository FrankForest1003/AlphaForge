from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    worker_urls: tuple[str, ...]
    worker_token: str
    universe_path: Path
    trace_root: Path
    history_root: Path
    database_path: Path
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
    configured_urls = os.getenv("ALPHAFORGE_WORKER_URLS", "").strip()
    worker_urls = tuple(
        item.strip().rstrip("/")
        for item in configured_urls.split(",")
        if item.strip()
    )
    if not worker_urls:
        worker_urls = (
            os.getenv(
                "ALPHAFORGE_WORKER_URL", "http://127.0.0.1:18081"
            ).rstrip("/"),
        )
    return Settings(
        worker_urls=worker_urls,
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
        trace_root=Path(
            os.getenv(
                "ALPHAFORGE_TRACE_ROOT",
                REPOSITORY_ROOT / "backend" / "workspace" / "forge_traces",
            )
        ).resolve(),
        history_root=Path(
            os.getenv(
                "ALPHAFORGE_HISTORY_ROOT",
                REPOSITORY_ROOT / "backend" / "workspace" / "run_history",
            )
        ).resolve(),
        database_path=Path(
            os.getenv(
                "ALPHAFORGE_DATABASE_PATH",
                REPOSITORY_ROOT / "backend" / "workspace" / "database" / "alphaforge.db",
            )
        ).resolve(),
        api_key=os.getenv("API_KEY", "").strip(),
        base_url=os.getenv("BASE_URL", "https://api.deepseek.com").rstrip("/"),
        model=os.getenv("MODEL", "deepseek-v4-pro").strip(),
        thinking_enabled=_env_bool("THINKING_ENABLED", True),
    )
