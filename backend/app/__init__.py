import sys
from pathlib import Path

# Общий пакет доступа к базам (pkdb) лежит в корне проекта: при запуске из backend/ добавляем корень в путь поиска
_root = Path(__file__).resolve().parents[2]
if (_root / "pkdb").is_dir() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
