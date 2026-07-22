from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    worker_base_url: str
    worker_token: str
    universe_path: Path


def load_settings() -> Settings:
    database_path = Path(
        os.getenv("ALPHAFORGE_DB_PATH", REPOSITORY_ROOT / "backend" / "alphaforge.db")
    ).resolve()
    universe_path = Path(
        os.getenv(
            "ALPHAFORGE_UNIVERSE_CONFIG",
            REPOSITORY_ROOT / "lean_worker" / "config" / "universe_whitelist_v1.0.json",
        )
    ).resolve()
    return Settings(
        database_path=database_path,
        worker_base_url=os.getenv("ALPHAFORGE_WORKER_URL", "http://127.0.0.1:18081").rstrip("/"),
        worker_token=os.getenv("ALPHAFORGE_WORKER_TOKEN", ""),
        universe_path=universe_path,
    )
