@echo off
rem Локальный запуск платформы без Docker.
rem   Сайт и API — http://localhost:8765 (в админ-панели работает кнопка «Запустить сбор сейчас»). Другой порт: set PK_PORT=...
rem   Данные — в PostgreSQL. Если PK_PG_URL не задан, запускается встроенный PostgreSQL (pgserver) с данными в %%LOCALAPPDATA%%\sm01-pg.
rem   При первом запуске база предприятий переносится из папки data\ (если она есть), дальше файлы не нужны.
rem   Отдельное окно — планировщик сбора из реестров: каждый день в 00:01 и по кнопке в админ-панели.
rem   Ещё одно окно — краулер: после каждого сбора ищет и обходит сайты предприятий, берёт задания повторного обхода из админ-панели.
rem   Кеш и служебные файлы (байт-код Python, скачанные открытые данные, кеш краулера) — в папке Trash, очистка — clean.cmd.
rem Нужен uv: https://docs.astral.sh/uv/ . Не закрывайте окна, пока платформа нужна.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONPYCACHEPREFIX=%~dp0Trash\pycache
if "%PK_PORT%"=="" set PK_PORT=8765
set UVRUN=uv run --no-project --python 3.12 --with-requirements backend\requirements.txt

where uv >nul 2>nul
if errorlevel 1 (
  echo Не найден uv. Установите его командой:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  pause
  exit /b 1
)

if "%PK_PG_URL%"=="" (
  echo Запуск встроенного PostgreSQL...
  for /f "usebackq delims=" %%u in (`%UVRUN% --with pgserver python tools\local_pg.py`) do set PK_PG_URL=%%u
)
if "%PK_PG_URL%"=="" ( echo Не удалось запустить PostgreSQL. & pause & exit /b 1 )

echo Базы данных: создание и обновление схем...
%UVRUN% python -m pkdb.migrate || (pause & exit /b 1)
%UVRUN% python tools\json_to_pg.py --if-empty || (pause & exit /b 1)
%UVRUN% python -m pkdb.seed || (pause & exit /b 1)

echo Сборка сайта...
%UVRUN% python tools\build_site.py || (pause & exit /b 1)

start "Промышленная кооперация — сбор данных" cmd /k %UVRUN% python -u -m sync --daemon
start "Промышленная кооперация — краулер" cmd /k %UVRUN% --with scrapy --with pyyaml python -u crawler\daemon.py
start "" cmd /c "timeout /t 5 >nul & start http://localhost:%PK_PORT%/"

echo Сервер платформы: http://localhost:%PK_PORT%  (остановить — Ctrl+C)
%UVRUN% uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PK_PORT%
