from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)


def load_model_settings(env_file: Path = Path(".env")) -> ModelSettings:
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    resolved = {
        key: os.environ.get(key, values.get(key, ""))
        for key in ("API_KEY", "MODEL", "BASE_URL")
    }
    return ModelSettings(
        api_key=resolved["API_KEY"],
        model=resolved["MODEL"],
        base_url=resolved["BASE_URL"],
    )
