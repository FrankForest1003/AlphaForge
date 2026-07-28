from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def write_json(path: str | Path, value: Any) -> Path:
    """Write one UTF-8 JSON artifact atomically."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def relative_artifact(path: Path, experiment_dir: Path) -> str:
    return path.resolve().relative_to(experiment_dir.resolve()).as_posix()
