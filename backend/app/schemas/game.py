from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
            raise ValueError(
                "username may contain only letters, numbers, hyphens, and underscores"
            )
        return normalized


class BattleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="New Alpha Battle", min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())
