"""Атомарная публикация небольших текстовых и бинарных артефактов."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable, TextIO


def atomic_write(
    path: Path,
    writer: Callable[[BinaryIO | TextIO], None],
    *,
    text: bool = False,
) -> None:
    """Записывает временный файл рядом с целью и публикует его одной заменой."""
    path = Path(path)
    temp_path: Path | None = None
    options = {
        "mode": "w" if text else "wb",
        "dir": path.parent,
        "prefix": f".{path.name}.",
        "suffix": ".tmp",
        "delete": False,
    }
    if text:
        options.update(encoding="utf-8", newline="\n")

    try:
        with tempfile.NamedTemporaryFile(**options) as temp:
            temp_path = Path(temp.name)
            writer(temp)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    """Атомарно публикует UTF-8 текст."""
    atomic_write(path, lambda stream: stream.write(content), text=True)


def atomic_copy(source: Path, destination: Path) -> None:
    """Потоково копирует файл и атомарно заменяет целевой артефакт."""
    source = Path(source)

    def copy(stream: BinaryIO | TextIO) -> None:
        with source.open("rb") as original:
            shutil.copyfileobj(original, stream)

    atomic_write(destination, copy)
