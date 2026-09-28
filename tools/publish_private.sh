#!/usr/bin/env bash
# Публикация полной копии проекта в закрытый репозиторий.
#
# Основной (публичный) репозиторий получает обычные коммиты с учётом .gitignore.
# Закрытый репозиторий хранит ровно один коммит со всеми файлами проекта,
# включая игнорируемые (.gitignore и глобальные исключения не применяются).
# При каждом запуске история закрытого репозитория заменяется новым единственным коммитом.
#
# Запуск из корня проекта:  bash tools/publish_private.sh
set -euo pipefail

PRIVATE_URL="${PK_PRIVATE_REPO:-https://github.com/DigitalRevision/Cooperation-Web-Agent-Private.git}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Копия рабочего дерева без служебной папки .git, папки Trash (кеш и служебные файлы: скачанные архивы ФНС до 220 МБ — GitHub
# принимает файлы до 100 МБ, парсер скачивает их заново при первом запуске), виртуального окружения и данных: данные платформы
# хранятся только в PostgreSQL (docs/DATABASE.md), их резервная копия — pg_dump, а не Git. data/ и site/data.json — прежний
# JSON-репозиторий и выгрузка каталога
tar -C "$ROOT" --exclude=./.git --exclude=./Trash --exclude=./.venv --exclude=./data --exclude=./site/data.json   --exclude=./site/dist/data.json --exclude='*/__pycache__' --exclude=./.pytest_cache -cf - . | tar -C "$TMP" -xf -

# Автор коммита — тот же, что в основном репозитории
NAME="$(git -C "$ROOT" config user.name)"
EMAIL="$(git -C "$ROOT" config user.email)"
REV="$(git -C "$ROOT" rev-parse --short HEAD)"

cd "$TMP"
git init -q -b main
git -c core.excludesFile=/dev/null -c core.autocrlf=false -c core.safecrlf=false add -A --force
git -c user.name="$NAME" -c user.email="$EMAIL" commit -q -m "Full project snapshot at $REV"
git push -q --force "$PRIVATE_URL" main
echo "Закрытый репозиторий обновлён: один коммит, снимок $REV, файлов: $(git ls-files | wc -l)"
