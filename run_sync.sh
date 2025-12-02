#!/usr/bin/env bash

# Путь к проекту
PROJECT_DIR="/root/spotify-yandex-sync"

cd "$PROJECT_DIR" || exit 1

# Активируем venv
source venv/bin/activate

# Запускаем синк, всё логируем в файл
python sync_spotify_to_yandex.py >> sync.log 2>&1
