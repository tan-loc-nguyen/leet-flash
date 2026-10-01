"""Crash-safe JSON writes and append-only JSONL writes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via temp file + flush + fsync + atomic replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, *, sort_keys: bool = False) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=sort_keys) + "\n"
    atomic_write_text(path, text)


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}). Fix it or restore from Git/backup.") from exc


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append exactly one JSON line. Never rewrites existing content."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "ab+") as fh:
        # Guard against a previous interrupted write that left no trailing newline.
        fh.seek(0, os.SEEK_END)
        if fh.tell() > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
