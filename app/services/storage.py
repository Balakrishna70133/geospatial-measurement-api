from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_result(storage_dir: Path, file_id: str, payload: dict[str, Any]) -> None:
    path = storage_dir / f"{file_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_result(storage_dir: Path, file_id: str) -> dict[str, Any] | None:
    path = storage_dir / f"{file_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
