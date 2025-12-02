#!/usr/bin/env bash

# Директория, где лежит сам скрипт
SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd)"

cd "$SCRIPT_DIR" || exit 1

# Активируем venv
source venv/bin/activate

# Лог пишем рядом с проектом
python sync_spotify_to_yandex.py >> "$SCRIPT_DIR/sync.log" 2>&1
