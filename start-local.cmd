@echo off
rem Локальный запуск платформы без Docker.
rem   Сайт и API — http://localhost:8765 (в админ-панели работает кнопка «Запустить сбор сейчас»). Другой порт: set PK_PORT=...
rem   Отдельное окно — планировщик сбора из реестров: каждый день в 00:01 и по кнопке в админ-панели.
rem Нужен uv: https://docs.astral.sh/uv/ . Не закрывайте окна, пока платформа нужна.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if "%PK_PORT%"=="" set PK_PORT=8765

where uv >nul 2>nul
if errorlevel 1 (
  echo Не найден uv. Установите его командой:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  pause
  exit /b 1
)

echo Сборка сайта...
uv run --no-project --python 3.12 python tools\build_site.py || (pause & exit /b 1)

start "Промышленная кооперация — сбор данных" cmd /k uv run --no-project --python 3.12 --with httpx python -u -m sync --daemon
start "" cmd /c "timeout /t 5 >nul & start http://localhost:%PK_PORT%/"

echo Сервер платформы: http://localhost:%PK_PORT%  (остановить — Ctrl+C)
uv run --no-project --python 3.12 --with-requirements backend\requirements.txt uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PK_PORT%
