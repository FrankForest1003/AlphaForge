from __future__ import annotations

import os
from pathlib import Path
import threading


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Replace a text file without exposing a truncated intermediate state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
