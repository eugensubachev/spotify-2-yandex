#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from dotenv import load_dotenv

from yandex_music import Client
from yandex_music.exceptions import TimedOutError, UnauthorizedError

# ===================== НАСТРОЙКИ / ENV =====================

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8888/callback",
)
SPOTIFY_SCOPE = "user-library-read"

YANDEX_MUSIC_TOKEN = os.getenv("YANDEX_MUSIC_TOKEN")

STATE_FILE = os.getenv("STATE_FILE", "spotify_yandex_state.json")

STATE_DEFAULT = {
    "processed_spotify_ids": [],
    "last_spotify_added_at": None,  # ISO-строка, например "2025-12-02T10:33:56Z"
}

# ===========================================================


def init_spotify_client() -> spotipy.Spotify:
    """Инициализируем клиента Spotify (spotipy) с понятными ошибками."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("❌ SPOTIFY_CLIENT_ID или SPOTIFY_CLIENT_SECRET не заданы.")
        print("   Откройте .env и заполните значения Spotify API.")
        raise RuntimeError("Не заданы ключи Spotify (SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET) в .env")

    print("Инициализация Spotify клиента...")
    print("   Использую redirect_uri:", repr(SPOTIFY_REDIRECT_URI))

    try:
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SPOTIFY_SCOPE,
            cache_path=".spotify_token_cache",
            open_browser=True,  # на сервере можно переключить на False
        )

        # Можно сразу дернуть что-то простое, чтобы форсировать проверку токена/настроек
        sp = spotipy.Spotify(auth_manager=auth_manager)
        return sp

    except SpotifyOauthError as e:
        msg = str(e)

        print("\n❌ Ошибка авторизации в Spotify.")
        print("   Проверьте, правильно ли заполнен файл .env:")

        print("   - SPOTIFY_CLIENT_ID")
        print("   - SPOTIFY_CLIENT_SECRET")
        print("   - SPOTIFY_REDIRECT_URI (должен совпадать с настройками в Spotify Dashboard)")

        if "INVALID_CLIENT" in msg or "invalid_client" in msg:
            print("\n   Детали: Spotify вернул INVALID_CLIENT —")
            print("   это почти всегда означает неправильный Client ID / Secret.")
        if "redirect_uri" in msg:
            print("\n   Детали: проблема с redirect_uri.")
            print("   Убедитесь, что в Spotify Dashboard добавлен ровно такой Redirect URI:")
            print("   ", SPOTIFY_REDIRECT_URI)

        print(f"\n   Техническое сообщение от Spotify: {msg}\n")
        raise

    except Exception as e:
        print("\n❌ Не удалось инициализировать клиента Spotify.")
        print(f"   Ошибка: {e}")
        print("   Проверьте интернет и настройки .env.")
        raise


def init_yandex_client() -> Client:
    """Инициализируем клиента Яндекс.Музыки."""
    if not YANDEX_MUSIC_TOKEN:
        print("❌ YANDEX_MUSIC_TOKEN не задан. Проверьте файл .env")
        raise RuntimeError("Не задан токен Яндекс.Музыки (YANDEX_MUSIC_TOKEN) в .env")

    print("Инициализация Yandex Music клиента...")
    client = Client(YANDEX_MUSIC_TOKEN).init()
    return client


def parse_spotify_ts(ts: Optional[str]) -> Optional[datetime]:
    """Парсим ISO-строку Spotify (с Z на конце) в datetime с tz=UTC."""
    if not ts:
        return None
    # Spotify отдаёт что-то вроде "2025-12-02T10:33:56Z"
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except ValueError:
        return None


def format_spotify_ts(dt: Optional[datetime]) -> Optional[str]:
    """Форматируем datetime в строку вида 2025-12-02T10:33:56Z."""
    if not dt:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state() -> Dict[str, Any]:
    """Загружаем состояние (обработанные spotify_id + last_spotify_added_at) из JSON-файла."""
    if not os.path.exists(STATE_FILE):
        return dict(STATE_DEFAULT)

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # файл битый — начинаем с нуля
        return dict(STATE_DEFAULT)

    # гарантируем наличие нужных полей
    for k, v in STATE_DEFAULT.items():
        data.setdefault(k, v)

    # processed_spotify_ids приведём к списку строк
    if not isinstance(data.get("processed_spotify_ids"), list):
        data["processed_spotify_ids"] = []
    data["processed_spotify_ids"] = [str(x) for x in data["processed_spotify_ids"]]

    return data


def save_state(state: Dict[str, Any]) -> None:
    """Сохраняем состояние в JSON-файл (через временный файл)."""
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATE_FILE)


def fetch_yandex_liked_ids(ym: Client) -> Set[str]:
    """
    Получаем множество уже лайкнутых треков Я.Музыки в формате "track_id:album_id",
    чтобы не дублировать лайки.
    """
    print("Получаем текущие лайки Яндекс.Музыки...")
    result: Set[str] = set()
    try:
        likes = ym.users_likes_tracks()
        for item in likes:
            track_id = getattr(item, "id", None)
            album_id = getattr(item, "album_id", None)
            if track_id and album_id:
                result.add(f"{track_id}:{album_id}")
    except Exception as e:
        print(f"   Не удалось получить лайки Я.Музыки: {e}")
    print(f"Всего лайков в Яндекс.Музыке сейчас: {len(result)}")
    return result


def fetch_spotify_liked_tracks(
    sp: spotipy.Spotify,
    last_added_at: Optional[str],
    page_limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Получаем ТОЛЬКО НОВЫЕ любимые треки из Spotify.

    Логика:
      - если last_added_at = None → берем вообще все лайки (первый импорт);
      - если задана → идём от свежих к старым, пока added_at > last_added_at;
      - найденные "новые" потом разворачиваем, чтобы обрабатывать от старых к новым
        и сохранить хронологию как в Spotify.
    """
    since_dt = parse_spotify_ts(last_added_at)

    if since_dt:
        print(f"Получаем НОВЫЕ любимые треки из Spotify (после {last_added_at})...")
    else:
        print("Получаем ВСЕ любимые треки из Spotify (первый импорт)...")

    new_tracks: List[Dict[str, Any]] = []
    offset = 0

    while True:
        page = sp.current_user_saved_tracks(limit=page_limit, offset=offset)
        items = page.get("items", [])
        if not items:
            break

        stop = False

        for item in items:
            track = item.get("track") or {}
            if not track:
                continue

            track_id = track.get("id")
            if not track_id:
                continue

            added_raw = item.get("added_at")  # строка ISO от Spotify
            added_dt = parse_spotify_ts(added_raw)

            # если задан since_dt и текущий лайк старее или равен — дальше можно не идти
            if since_dt and added_dt and added_dt <= since_dt:
                stop = True
                break

            artists = [a.get("name", "") for a in track.get("artists", [])]
            album = track.get("album") or {}

            new_tracks.append(
                {
                    "id": track_id,
                    "name": track.get("name", ""),
                    "artists": artists,
                    "album_name": album.get("name", ""),
                    "duration_ms": track.get("duration_ms", 0),
                    "added_at": added_raw,
                }
            )

        if stop:
            break

        offset += len(items)
        if len(items) < page_limit:
            break

    # Spotify отдаёт от новых к старым, а нам для сохранения хронологии
    # выгодно идти от старых к новым.
    new_tracks.reverse()

    print(f"Новых треков из Spotify для обработки: {len(new_tracks)}")
    return new_tracks


def build_yandex_like_id(track_obj: Any) -> Optional[str]:
    """
    Собираем строку вида 'track_id:album_id' для users_likes_tracks_add().
    """
    track_id = getattr(track_obj, "id", None)
    albums = getattr(track_obj, "albums", None)

    if not track_id or not albums:
        return None

    album = albums[0]
    album_id = getattr(album, "id", None)
    if not album_id:
        return None

    return f"{track_id}:{album_id}"


def find_best_yandex_match(ym: Client, track: Dict[str, Any]) -> Optional[Any]:
    """
    Ищем лучший матч трека в Яндекс.Музыке.
    Возвращаем объект Track или None.
    """
    name = track["name"]
    artists_list = track["artists"]
    artists_str = ", ".join(artists_list)
    query = f"{artists_str} — {name}"

    last_error: Optional[Exception] = None

    for attempt in range(3):
        try:
            search_result = ym.search(text=query, type_="track")
            break
        except TimedOutError as e:
            last_error = e
            print(f"   Yandex API timeout при поиске '{query}' (попытка {attempt + 1}/3)")
            time.sleep(3)
    else:
        print(f"   Не удалось обратиться к Я.Музыке для '{query}': {last_error}")
        return None

    try:
        if (
            not search_result
            or not getattr(search_result, "tracks", None)
            or not search_result.tracks.results
        ):
            return None

        # простая стратегия — берём первый результат
        return search_result.tracks.results[0]
    except Exception as e:
        print(f"   Ошибка при обработке результатов Я.Музыки для '{query}': {e}")
        return None


def like_yandex_track(
    ym: Client,
    ya_track: Any,
    title_for_log: str,
    existing_likes: Set[str],
) -> bool:
    """
    Лайкаем трек в Яндекс.Музыке, если его там ещё нет.
    Возвращаем True при успехе (или если уже лайкнут), False при фейле.
    """
    like_id = build_yandex_like_id(ya_track)
    if not like_id:
        print(f"   Не удалось собрать like_id для '{title_for_log}'")
        return False

    if like_id in existing_likes:
        print(f"   Уже есть в 'Мне нравится' — лайк не дублирую.")
        return True

    for attempt in range(3):
        try:
            ym.users_likes_tracks_add([like_id])
            existing_likes.add(like_id)
            return True
        except TimedOutError:
            print(
                f"   Yandex API timeout при лайке '{title_for_log}' "
                f"(попытка {attempt + 1}/3)"
            )
            time.sleep(3)
        except Exception as e:
            print(f"   Ошибка при лайке трека в Яндекс.Музыке '{title_for_log}': {e}")
            return False

    print(f"   Не удалось лайкнуть '{title_for_log}' после 3 попыток — пропускаю.")
    return False


def main() -> None:
    sp = init_spotify_client()
    ym = init_yandex_client()

    state = load_state()
    processed_ids: Set[str] = set(state.get("processed_spotify_ids", []))
    last_added_at_str: Optional[str] = state.get("last_spotify_added_at")

    ya_existing_likes = fetch_yandex_liked_ids(ym)

    spotify_liked = fetch_spotify_liked_tracks(sp, last_added_at_str)

    if not spotify_liked:
        print("Новых любимых треков в Spotify нет — синхронизировать нечего.")
        return

    total = len(spotify_liked)
    added = 0
    skipped_already_processed = 0
    not_found = 0

    max_added_dt: Optional[datetime] = parse_spotify_ts(last_added_at_str)

    for idx, track in enumerate(spotify_liked, start=1):
        spotify_id = track["id"]
        name = track["name"]
        artists_str = ", ".join(track["artists"])
        human_title = f"{artists_str} — {name}"

        added_dt = parse_spotify_ts(track.get("added_at"))
        if added_dt and (max_added_dt is None or added_dt > max_added_dt):
            max_added_dt = added_dt

        if spotify_id in processed_ids:
            skipped_already_processed += 1
            continue

        print(f"[{idx}/{total}] Ищу в Яндексе: {human_title}")

        ya_track = find_best_yandex_match(ym, track)

        if ya_track is None:
            print("   Не найдено подходящего трека в Яндекс.Музыке.")
            not_found += 1
            processed_ids.add(spotify_id)
            state["processed_spotify_ids"] = list(processed_ids)
            if max_added_dt:
                state["last_spotify_added_at"] = format_spotify_ts(max_added_dt)
            save_state(state)
            continue

        success = like_yandex_track(ym, ya_track, human_title, ya_existing_likes)

        if success:
            ya_artists = ", ".join(a.name for a in ya_track.artists)
            ya_title = f"{ya_artists} — {ya_track.title}"
            print(f"   Добавлен в 'Мне нравится': {ya_title}")
            added += 1
        else:
            print("   Не удалось добавить трек в 'Мне нравится'.")

        processed_ids.add(spotify_id)
        state["processed_spotify_ids"] = list(processed_ids)
        if max_added_dt:
            state["last_spotify_added_at"] = format_spotify_ts(max_added_dt)
        save_state(state)

    print("\n=== Готово ===")
    print(f"Новых треков из Spotify обработано: {total}")
    print(f"Добавлено в 'Мне нравится': {added}")
    print(f"Пропущено (обработаны ранее): {skipped_already_processed}")
    print(f"Не найдено в Яндекс.Музыке: {not_found}")

import sys
if __name__ == "__main__":
    try:
        main()

    # Наши ожидаемые ошибки конфигурации / авторизации
    except (RuntimeError, SpotifyOauthError, UnauthorizedError) as e:
        print("\n❌ Скрипт остановлен из-за ошибки конфигурации или авторизации.")
        print(f"   Сообщение: {e}")
        print("   ➜ Проверьте, правильно ли заполнен файл .env (ключи Spotify и токен Яндекс.Музыки).\n")
        sys.exit(1)

    # Любые другие непредвиденные ошибки
    except Exception as e:
        print("\n❌ Непредвиденная ошибка во время выполнения скрипта.")
        print(f"   Тип: {type(e).__name__}")
        print(f"   Сообщение: {e}")
        print("   Если ошибка повторяется — создайте issue в репозитории.\n")
        sys.exit(1)
