"""Очистка кеша и служебных файлов проекта: папка Trash целиком, а также байт-код Python (__pycache__) и кеш pytest,
которые тесты и редактор кода оставляют рядом с исходниками.

  python tools/clean.py        (или clean.cmd в корне проекта)

В Trash лежат:
  opendata — скачанные открытые данные ФНС и Минпромторга (sync): после очистки сбор скачает их заново — около 1 ГБ,
             с реестром МСП (PK_SYNC_RMSP=1) ещё около 2 ГБ;
  scrapy   — кеш страниц краулера;
  pycache  — байт-код Python при запуске через start-local.cmd (после очистки первый запуск чуть дольше);
  pytest   — кеш pytest;
  logs     — журнал сбора, запущенного кнопкой в админ-панели без планировщика;
  e2e      — профили браузера сквозной проверки tools/e2e_site.mjs, если не удалились сами.
Данные платформы (PostgreSQL) и виртуальное окружение .venv не затрагиваются. Перед очисткой остановите платформу:
файлы, открытые работающими процессами, не удалятся.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRAY = {"__pycache__", ".pytest_cache"}
SKIP = {".venv", ".git", "node_modules", "Trash"}


def targets():
    if (ROOT / "Trash").is_dir():
        yield ROOT / "Trash"
    stack = [ROOT]
    while stack:
        for d in stack.pop().iterdir():
            if d.is_dir() and d.name not in SKIP:
                if d.name in STRAY:
                    yield d
                else:
                    stack.append(d)


def size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def main():
    freed, failed = 0, []
    for d in targets():
        n = size(d)
        try:
            shutil.rmtree(d)
        except OSError as e:
            failed.append(f"{d.relative_to(ROOT)}: {e}")
            n -= size(d) if d.exists() else 0
        freed += n
        print(f"  {d.relative_to(ROOT)}  {n / 1e6:.1f} МБ")
    print(f"освобождено {freed / 1e6:.1f} МБ" if freed else "кеша нет")
    if failed:
        print("не удалось удалить (файлы заняты работающей платформой?):", *failed, sep="\n  ")


if __name__ == "__main__":
    main()
