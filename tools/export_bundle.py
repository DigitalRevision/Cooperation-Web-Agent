"""Атомарно выгружает свежий каталог из PostgreSQL для автономного сайта."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__:
    from .atomic_files import atomic_copy, atomic_write
else:
    from atomic_files import atomic_copy, atomic_write

ROOT = Path(__file__).resolve().parents[1]


def publish_bundle(data: dict[str, Any], site_root: Path) -> tuple[Path, int]:
    """Потоково сохраняет JSON-пакет и публикует его в dist без частично записанного файла."""
    site_root = Path(site_root)
    output = site_root / "data.json"

    def write_json(stream) -> None:
        json.dump(data, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    atomic_write(output, write_json, text=True)
    dist = site_root / "dist"
    if dist.is_dir():
        atomic_copy(output, dist / output.name)
    return output, output.stat().st_size


def main() -> None:
    """Получает пакет из актуального снимка API и публикует его в папке сайта."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app import bundle
    from app.repo import get_repo

    output, size = publish_bundle(bundle.build(get_repo()), ROOT / "site")
    print(f"{output}: {size / 1_000_000:.1f} МБ")


if __name__ == "__main__":
    main()
