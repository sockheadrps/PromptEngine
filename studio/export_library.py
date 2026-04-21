from __future__ import annotations

import re
import time
from pathlib import Path
from threading import Lock
from typing import Any


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(name: str) -> str:
    cleaned = _SAFE.sub("_", name.strip()).strip("._")
    if not cleaned:
        raise ValueError("name required")
    return cleaned


class ExportLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _file(self, name: str) -> Path:
        return self.path / f"{_safe_name(name)}.py"

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for p in self.path.glob("*.py"):
                try:
                    stat = p.stat()
                except OSError:
                    continue
                rows.append({"name": p.stem, "saved_at": stat.st_mtime, "size": stat.st_size})
            rows.sort(key=lambda r: r["saved_at"], reverse=True)
            return rows

    def get(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            p = self._file(name)
            if not p.exists():
                return None
            try:
                code = p.read_text(encoding="utf-8")
                stat = p.stat()
            except OSError:
                return None
            return {"name": p.stem, "code": code, "saved_at": stat.st_mtime}

    def save(self, name: str, code: str) -> dict[str, Any]:
        with self._lock:
            p = self._file(name)
            tmp = p.with_suffix(".py.tmp")
            tmp.write_text(code, encoding="utf-8")
            tmp.replace(p)
            return {"name": p.stem, "saved_at": time.time(), "size": p.stat().st_size}

    def delete(self, name: str) -> bool:
        with self._lock:
            p = self._file(name)
            if not p.exists():
                return False
            p.unlink()
            return True
