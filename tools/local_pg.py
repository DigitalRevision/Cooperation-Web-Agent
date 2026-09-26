"""Локальный PostgreSQL для запуска без Docker (start-local.cmd): встроенный сервер pgserver.

Печатает адрес сервера для PK_PG_URL. Данные лежат в %LOCALAPPDATA%\sm01-pg (Windows) или ~/sm01-pg и переживают перезапуск.
Если у вас уже есть свой PostgreSQL, задайте PK_PG_URL — этот скрипт не понадобится.
"""
import os
from pathlib import Path

import pgserver

d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "sm01-pg"
print(pgserver.get_server(str(d), cleanup_mode=None).get_uri())
