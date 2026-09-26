"""Выгрузка каталога из PostgreSQL в site/data.json — для просмотра сайта без сервера платформы (файл, предпросмотр).

  python tools/export_bundle.py            # site/data.json (+ site/dist/data.json, если сайт собран)

Файл в том же облегчённом формате, что отдаёт GET /api/v1/bundle. В Git он не хранится (.gitignore): рабочий сайт
получает каталог с сервера.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import bundle  # noqa: E402  (импорт app добавляет в путь пакет pkdb)
from app.repo import get_repo  # noqa: E402

out = ROOT / "site" / "data.json"
body = json.dumps(bundle.build(get_repo()), ensure_ascii=False, separators=(",", ":"))
out.write_text(body, encoding="utf-8")
if (ROOT / "site" / "dist").is_dir():
    shutil.copy(out, ROOT / "site" / "dist" / "data.json")
print(f"{out}: {len(body.encode('utf-8')) / 1e6:.1f} МБ")
