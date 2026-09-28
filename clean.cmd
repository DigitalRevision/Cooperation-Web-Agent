@echo off
rem Очистка кеша и служебных файлов проекта: папка Trash, __pycache__ и .pytest_cache рядом с исходниками (tools\clean.py).
rem Данные платформы (PostgreSQL) не затрагиваются. Перед очисткой остановите платформу (окна start-local.cmd).
chcp 65001 >nul
cd /d "%~dp0"
uv run --no-project --python 3.12 python tools\clean.py
pause
