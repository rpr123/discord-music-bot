from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
YTDL_WORKER_PATH = PROJECT_DIR / "ytdl_worker.py"


def load_env_file(path: Path | str = PROJECT_DIR / ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_env_file()


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("music-bot")


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
FFMPEG_EXECUTABLE = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
MUSIC_CHANNEL_ID = os.getenv("MUSIC_CHANNEL_ID")
MUSIC_CHANNEL_NAME = os.getenv("MUSIC_CHANNEL_NAME", "music")
MUSIC_CHANNELS_FILE = resolve_project_path(
    os.getenv("MUSIC_CHANNELS_FILE", "music_channels.json")
)
MUSIC_CHANNEL_SILENT = os.getenv("MUSIC_CHANNEL_SILENT", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
MUSIC_CHANNEL_DELETE_REQUESTS = os.getenv(
    "MUSIC_CHANNEL_DELETE_REQUESTS", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE")


def parse_positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("%s must be a positive integer. Falling back to %s.", name, default)
        return default


def parse_nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be zero or greater. Falling back to %s.", name, default)
        return default

    if value < 0:
        logger.warning("%s must be zero or greater. Falling back to %s.", name, default)
        return default
    return value


def parse_string_map_env(name: str) -> dict[str, str]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("%s must be a JSON object. Ignoring its value.", name)
        return {}
    if not isinstance(payload, dict):
        logger.warning("%s must be a JSON object. Ignoring its value.", name)
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }


MAX_BULK_TRACKS = parse_positive_int_env("MAX_BULK_TRACKS", 50)
MUSIC_FEEDBACK_DELETE_SECONDS = parse_positive_int_env("MUSIC_FEEDBACK_DELETE_SECONDS", 10)
EPHEMERAL_RESPONSE_DELETE_SECONDS = parse_positive_int_env(
    "EPHEMERAL_RESPONSE_DELETE_SECONDS", 15
)
QUEUE_DELETE_RESPONSE_DELETE_SECONDS = parse_positive_int_env(
    "QUEUE_DELETE_RESPONSE_DELETE_SECONDS", 30
)
DEFAULT_AUTO_TRACKS = parse_positive_int_env("DEFAULT_AUTO_TRACKS", 8)
MAX_AUTO_TRACKS = parse_positive_int_env("MAX_AUTO_TRACKS", 25)
AUTOPLAY_HISTORY_TTL_SECONDS = parse_positive_int_env(
    "AUTOPLAY_HISTORY_TTL_SECONDS", 12 * 60 * 60
)
AUTOPLAY_REFILL_CANDIDATES = min(
    parse_positive_int_env("AUTOPLAY_REFILL_CANDIDATES", 10),
    MAX_AUTO_TRACKS,
)
AUTOPLAY_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "AUTOPLAY_MIN_INTERVAL_SECONDS",
    15.0,
)
QUEUE_SELECT_LIMIT = 25
LYRICS_API_URL = os.getenv("LYRICS_API_URL", "https://lrclib.net/api/search")
LYRICS_REQUEST_TIMEOUT_SECONDS = parse_positive_int_env(
    "LYRICS_REQUEST_TIMEOUT_SECONDS", 10
)
YOUTUBE_LYRICS_FALLBACK = os.getenv("YOUTUBE_LYRICS_FALLBACK", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
NAMUWIKI_LYRICS_ENABLED = os.getenv(
    "NAMUWIKI_LYRICS_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
NAMUWIKI_PAGE_BASE_URL = os.getenv(
    "NAMUWIKI_PAGE_BASE_URL", "https://namu.wiki/w"
).rstrip("/")
NAMUWIKI_API_BASE_URL = os.getenv(
    "NAMUWIKI_API_BASE_URL", "https://wiki-api.namu.la/api"
).rstrip("/")
NAMUWIKI_API_TOKEN = os.getenv("NAMUWIKI_API_TOKEN", "").strip() or None
NAMUWIKI_PREVIEW_FALLBACK_ENABLED = os.getenv(
    "NAMUWIKI_PREVIEW_FALLBACK_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
NAMUWIKI_REQUEST_TIMEOUT_SECONDS = parse_positive_int_env(
    "NAMUWIKI_REQUEST_TIMEOUT_SECONDS", 10
)
NAMUWIKI_REQUEST_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 1.1
)
NAMUWIKI_DOCUMENT_OVERRIDES = parse_string_map_env("NAMUWIKI_DOCUMENT_OVERRIDES")
YTDL_EXTRACT_TIMEOUT_SECONDS = parse_positive_int_env("YTDL_EXTRACT_TIMEOUT_SECONDS", 45)
YTDL_MAX_CONCURRENT_EXTRACTIONS = parse_positive_int_env(
    "YTDL_MAX_CONCURRENT_EXTRACTIONS", 1
)
STREAM_URL_MAX_AGE_SECONDS = parse_positive_int_env("STREAM_URL_MAX_AGE_SECONDS", 900)
YTDL_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env("YTDL_MIN_INTERVAL_SECONDS", 6.0)
YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS",
    YTDL_MIN_INTERVAL_SECONDS,
)
YTDL_CACHE_TTL_SECONDS = parse_positive_int_env("YTDL_CACHE_TTL_SECONDS", 180)
YTDL_CACHE_MAX_ENTRIES = parse_positive_int_env("YTDL_CACHE_MAX_ENTRIES", 16)
YOUTUBE_SEARCH_CANDIDATES = min(
    parse_positive_int_env("YOUTUBE_SEARCH_CANDIDATES", 10),
    20,
)
YOUTUBE_MUSIC_SEARCH_ENABLED = os.getenv(
    "YOUTUBE_MUSIC_SEARCH_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 1.0
)
YOUTUBE_MUSIC_AUTH_FILE = os.getenv("YOUTUBE_MUSIC_AUTH_FILE", "").strip() or None
YOUTUBE_MUSIC_OAUTH_CLIENT_ID = (
    os.getenv("YOUTUBE_MUSIC_OAUTH_CLIENT_ID", "").strip() or None
)
YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET = (
    os.getenv("YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET", "").strip() or None
)
YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS = parse_positive_int_env(
    "YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS", 5
)
YOUTUBE_MUSIC_LANGUAGE = os.getenv("YOUTUBE_MUSIC_LANGUAGE", "en").strip() or "en"
YOUTUBE_MUSIC_LOCATION = os.getenv("YOUTUBE_MUSIC_LOCATION", "").strip()
YOUTUBE_CIRCUIT_BREAKER_SECONDS = parse_positive_int_env(
    "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800
)
EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS = 3
IDLE_VOICE_DISCONNECT_DELAY_SECONDS = parse_nonnegative_float_env(
    "IDLE_VOICE_DISCONNECT_DELAY_SECONDS", 300.0
)
VOICE_RECONNECT_GRACE_SECONDS = 5.0
VOICE_DISCONNECT_TIMEOUT_SECONDS = 10.0
AUTOPLAY_START_DELAY_SECONDS = parse_nonnegative_float_env(
    "AUTOPLAY_START_DELAY_SECONDS", 10.0
)
LYRICS_START_DELAY_SECONDS = parse_nonnegative_float_env(
    "LYRICS_START_DELAY_SECONDS", 3.0
)
AUTOPLAY_BUTTON_CUSTOM_ID = "music:autoplay"
CONTROL_PANEL_HISTORY_LIMIT = 100
YTDL_BASE_OPTIONS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
}

if YOUTUBE_COOKIES_FILE:
    YTDL_BASE_OPTIONS["cookiefile"] = str(resolve_project_path(YOUTUBE_COOKIES_FILE))

YTDL_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": True,
    "extract_flat": False,
}

YTDL_SEARCH_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": True,
    "extract_flat": "in_playlist",
}

YTDL_PLAYLIST_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": False,
    "extract_flat": "in_playlist",
    "playlistend": MAX_BULK_TRACKS,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


configured_music_channels: dict[int, int] = {}
configured_control_messages: dict[int, int] = {}
configured_autoplay_enabled: dict[int, bool] = {}


def load_music_channel_config() -> None:
    if not MUSIC_CHANNELS_FILE.exists():
        configured_music_channels.clear()
        configured_control_messages.clear()
        configured_autoplay_enabled.clear()
        return

    try:
        raw_config = json.loads(MUSIC_CHANNELS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read %s", MUSIC_CHANNELS_FILE)
        return

    if not isinstance(raw_config, dict):
        logger.warning("Ignoring invalid music channel config in %s", MUSIC_CHANNELS_FILE)
        return

    configured_music_channels.clear()
    configured_control_messages.clear()
    configured_autoplay_enabled.clear()
    for guild_id, value in raw_config.items():
        if isinstance(value, dict):
            channel_id = value.get("channel_id")
            control_message_id = value.get("control_message_id")
            autoplay_enabled = value.get("autoplay_enabled", False)
        else:
            channel_id = value
            control_message_id = None
            autoplay_enabled = False

        try:
            parsed_guild_id = int(guild_id)
            configured_music_channels[parsed_guild_id] = int(channel_id)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid music channel config for guild %s", guild_id)
            continue

        if control_message_id is not None:
            try:
                configured_control_messages[parsed_guild_id] = int(control_message_id)
            except (TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid control message config for guild %s",
                    guild_id,
                )

        if isinstance(autoplay_enabled, bool):
            if autoplay_enabled:
                configured_autoplay_enabled[parsed_guild_id] = True
        else:
            logger.warning(
                "Ignoring invalid autoplay config for guild %s",
                guild_id,
            )


def save_music_channel_config() -> None:
    raw_config: dict[str, dict[str, int | bool]] = {}
    for guild_id, channel_id in sorted(configured_music_channels.items()):
        entry = {"channel_id": channel_id}
        control_message_id = configured_control_messages.get(guild_id)
        if control_message_id is not None:
            entry["control_message_id"] = control_message_id
        if configured_autoplay_enabled.get(guild_id, False):
            entry["autoplay_enabled"] = True
        raw_config[str(guild_id)] = entry

    MUSIC_CHANNELS_FILE.write_text(
        json.dumps(raw_config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get_music_channel_id(guild_id: int) -> int | None:
    if MUSIC_CHANNEL_ID:
        try:
            return int(MUSIC_CHANNEL_ID)
        except ValueError:
            logger.warning("MUSIC_CHANNEL_ID must be a numeric Discord channel ID")
            return None
    return configured_music_channels.get(guild_id)


def set_music_channel(guild_id: int, channel_id: int) -> None:
    if configured_music_channels.get(guild_id) != channel_id:
        configured_control_messages.pop(guild_id, None)
    configured_music_channels[guild_id] = channel_id
    save_music_channel_config()


def get_control_message_id(guild_id: int) -> int | None:
    return configured_control_messages.get(guild_id)


def set_control_message_id(guild_id: int, message_id: int) -> None:
    channel_id = get_music_channel_id(guild_id)
    if channel_id is None:
        return

    configured_music_channels.setdefault(guild_id, channel_id)
    if configured_control_messages.get(guild_id) == message_id:
        return

    configured_control_messages[guild_id] = message_id
    save_music_channel_config()


def clear_control_message_id(guild_id: int) -> None:
    if configured_control_messages.pop(guild_id, None) is not None:
        save_music_channel_config()


def get_autoplay_enabled(guild_id: int) -> bool:
    return configured_autoplay_enabled.get(guild_id, False)


def set_autoplay_enabled(guild_id: int, enabled: bool) -> None:
    channel_id = get_music_channel_id(guild_id)
    if channel_id is not None:
        configured_music_channels.setdefault(guild_id, channel_id)

    if enabled:
        configured_autoplay_enabled[guild_id] = True
    else:
        configured_autoplay_enabled.pop(guild_id, None)
    save_music_channel_config()
