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

# Копия рабочего дерева без служебной папки .git
tar -C "$ROOT" --exclude=./.git -cf - . | tar -C "$TMP" -xf -

# Автор коммита — тот же, что в основном репозитории
NAME="$(git -C "$ROOT" config user.name)"
EMAIL="$(git -C "$ROOT" config user.email)"
REV="$(git -C "$ROOT" rev-parse --short HEAD)"

cd "$TMP"
git init -q -b main
git -c core.excludesFile=/dev/null add -A --force
git -c user.name="$NAME" -c user.email="$EMAIL" commit -q -m "Full project snapshot at $REV"
git push -q --force "$PRIVATE_URL" main
echo "Закрытый репозиторий обновлён: один коммит, снимок $REV, файлов: $(git ls-files | wc -l)"
