from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import time
import urllib.parse
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands


PROJECT_DIR = Path(__file__).resolve().parent


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
MUSIC_CHANNEL_DELETE_REQUESTS = os.getenv("MUSIC_CHANNEL_DELETE_REQUESTS", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_MUSIC_ONLY = os.getenv("YOUTUBE_MUSIC_ONLY", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_SEARCH_FALLBACK = os.getenv("YOUTUBE_SEARCH_FALLBACK", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_MUSIC_SECTION = os.getenv("YOUTUBE_MUSIC_SECTION", "songs").strip().lower()
YOUTUBE_MUSIC_SECTIONS = {
    "albums",
    "artists",
    "community playlists",
    "featured playlists",
    "songs",
    "videos",
}
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE")


def parse_positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("%s must be a positive integer. Falling back to %s.", name, default)
        return default


def parse_volume_env(name: str, default: float) -> float:
    try:
        volume = float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be a number between 0.0 and 1.0. Falling back to %.2f.", name, default)
        return default

    if volume < 0.0 or volume > 1.0:
        logger.warning("%s must be between 0.0 and 1.0. Falling back to %.2f.", name, default)
        return default

    return volume


MAX_BULK_TRACKS = parse_positive_int_env("MAX_BULK_TRACKS", 50)
MUSIC_FEEDBACK_DELETE_SECONDS = parse_positive_int_env("MUSIC_FEEDBACK_DELETE_SECONDS", 10)
DEFAULT_AUTO_TRACKS = parse_positive_int_env("DEFAULT_AUTO_TRACKS", 8)
MAX_AUTO_TRACKS = parse_positive_int_env("MAX_AUTO_TRACKS", 25)
BOT_VOLUME = parse_volume_env("BOT_VOLUME", 0.2)
DISCORD_EMBED_FIELD_LIMIT = 1024
YTDL_EXTRACT_TIMEOUT_SECONDS = parse_positive_int_env("YTDL_EXTRACT_TIMEOUT_SECONDS", 45)
YTDL_MAX_CONCURRENT_EXTRACTIONS = parse_positive_int_env(
    "YTDL_MAX_CONCURRENT_EXTRACTIONS", 2
)
STREAM_URL_MAX_AGE_SECONDS = parse_positive_int_env("STREAM_URL_MAX_AGE_SECONDS", 900)

YTDL_BASE_OPTIONS = {
    "format": "bestaudio/best",
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

ytdl_semaphore = asyncio.Semaphore(YTDL_MAX_CONCURRENT_EXTRACTIONS)


async def extract_ytdl_info(
    options: dict,
    query: str,
    label: str,
) -> dict:
    logger.info("yt-dlp start: %s", label)
    logger.debug("yt-dlp query for %s: %s", label, query)

    def extract() -> dict:
        with yt_dlp.YoutubeDL(dict(options)) as downloader:
            return downloader.extract_info(query, download=False)

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    try:
        await asyncio.wait_for(
            ytdl_semaphore.acquire(),
            timeout=YTDL_EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("yt-dlp queue timed out: %s", label)
        raise

    worker = asyncio.create_task(asyncio.to_thread(extract))

    def extraction_finished(task: asyncio.Task[dict]) -> None:
        ytdl_semaphore.release()
        if task.cancelled():
            return
        task.exception()

    worker.add_done_callback(extraction_finished)
    remaining_timeout = max(
        0.1,
        YTDL_EXTRACT_TIMEOUT_SECONDS - (loop.time() - started_at),
    )
    try:
        info = await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=remaining_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "yt-dlp timed out after %s seconds: %s",
            YTDL_EXTRACT_TIMEOUT_SECONDS,
            label,
        )
        raise

    logger.info("yt-dlp done: %s", label)
    return info


def ffmpeg_is_available() -> bool:
    if Path(FFMPEG_EXECUTABLE).exists():
        return True
    return shutil.which(FFMPEG_EXECUTABLE) is not None


def is_silent_music_channel(channel: discord.abc.Messageable | None) -> bool:
    if not MUSIC_CHANNEL_SILENT or channel is None:
        return False

    guild = getattr(channel, "guild", None)
    channel_id = getattr(channel, "id", None)
    if guild is None or channel_id is None:
        return False

    return get_music_channel_id(guild.id) == channel_id


async def delete_music_request_message(message: discord.Message) -> None:
    if not MUSIC_CHANNEL_DELETE_REQUESTS:
        return

    try:
        await message.delete()
    except discord.NotFound:
        pass


async def delete_message_later(message: discord.Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.exception("Failed to delete temporary music feedback message")


async def notify_playback_error(state: GuildMusicState, content: str) -> None:
    if not state.announcement_channel:
        return

    try:
        await state.announcement_channel.send(
            content,
            silent=is_silent_music_channel(state.announcement_channel),
        )
    except discord.Forbidden:
        logger.warning("Missing permission to send playback error message")


@dataclass
class Track:
    title: str
    webpage_url: str
    requester: str
    source_url: str
    requester_id: int | None = None
    duration: int | None = None
    stream_url: str | None = None
    thumbnail_url: str | None = None
    stream_resolved_at: float | None = None
    track_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class GuildMusicState:
    queue: Deque[Track] = field(default_factory=deque)
    current: Track | None = None
    voice: discord.VoiceClient | None = None
    announcement_channel: discord.abc.Messageable | None = None
    control_message: discord.Message | None = None
    repeat_one: bool = False
    skip_requested: bool = False
    stop_requested: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    advance_task: asyncio.Task[None] | None = None
    playback_generation: int = 0


intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
music_states: dict[int, GuildMusicState] = {}
configured_music_channels: dict[int, int] = {}
commands_synced = False


def get_state(guild_id: int) -> GuildMusicState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState()
    return music_states[guild_id]


def load_music_channel_config() -> None:
    if not MUSIC_CHANNELS_FILE.exists():
        return

    try:
        raw_config = json.loads(MUSIC_CHANNELS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read %s", MUSIC_CHANNELS_FILE)
        return

    configured_music_channels.clear()
    for guild_id, channel_id in raw_config.items():
        try:
            configured_music_channels[int(guild_id)] = int(channel_id)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid music channel config for guild %s", guild_id)


def save_music_channel_config() -> None:
    raw_config = {
        str(guild_id): channel_id
        for guild_id, channel_id in sorted(configured_music_channels.items())
    }
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
    configured_music_channels[guild_id] = channel_id
    save_music_channel_config()


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "live"

    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def requester_label(track: Track) -> str:
    if track.requester_id is None:
        return track.requester
    return f"<@{track.requester_id}>"


def make_track_embed(track: Track, title: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=make_track_link(track, 4096))
    embed.add_field(name="Length", value=format_duration(track.duration), inline=True)
    embed.add_field(name="Requested by", value=track.requester, inline=True)
    if track.thumbnail_url:
        embed.set_thumbnail(url=track.thumbnail_url)
    return embed


def make_player_embed(track: Track, state: GuildMusicState) -> discord.Embed:
    queue_count = len(state.queue)
    repeat_text = "켜짐" if state.repeat_one else "꺼짐"
    embed = discord.Embed(
        title="💿 지금 재생 중",
        description=f"🎧 {requester_label(track)}님이 신청한 곡이에요!",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="YouTube Music",
        value=make_track_link(track, DISCORD_EMBED_FIELD_LIMIT),
        inline=False,
    )
    embed.add_field(name="길이", value=format_duration(track.duration), inline=True)
    embed.add_field(name="대기열", value=f"{queue_count}곡", inline=True)
    embed.add_field(name="반복", value=repeat_text, inline=True)
    if state.queue:
        preview = []
        for index, queued in enumerate(list(state.queue)[:5], start=1):
            preview.append(make_queue_line(index, queued))
        if len(state.queue) > 5:
            preview.append(f"...and {len(state.queue) - 5} more")
        embed.add_field(name="다음 곡", value="\n".join(preview), inline=False)
    #embed.set_footer(text=f"기본 볼륨 {int(BOT_VOLUME * 100)} · 버튼으로 바로 제어") 필요 없을듯?
    if track.thumbnail_url:
        embed.set_image(url=track.thumbnail_url)
    return embed


def make_bulk_embed(tracks: list[Track], title: str) -> discord.Embed:
    embed = discord.Embed(title=title)
    preview = [
        f"{index}. [{track.title}]({track.webpage_url})"
        for index, track in enumerate(tracks[:10], start=1)
    ]
    if len(tracks) > 10:
        preview.append(f"...and {len(tracks) - 10} more")

    embed.description = "\n".join(preview)
    embed.add_field(name="Added", value=str(len(tracks)), inline=True)
    embed.add_field(name="Limit", value=str(MAX_BULK_TRACKS), inline=True)
    return embed


def single_line(value: str) -> str:
    return " ".join(value.split())


def truncate_text(value: str, limit: int) -> str:
    value = single_line(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def make_track_link(track: Track, limit: int = DISCORD_EMBED_FIELD_LIMIT) -> str:
    title = truncate_text(track.title, 120)
    value = f"[{title}]({track.webpage_url})"
    if len(value) <= limit:
        return value
    return truncate_text(track.title, limit)


def make_queue_line(index: int, track: Track) -> str:
    return f"{index}. {truncate_text(track.title, 72)} - {format_duration(track.duration)}"


def make_queue_embed(state: GuildMusicState) -> discord.Embed:
    embed = discord.Embed(title="📋 대기열", color=discord.Color.blurple())

    if state.current:
        embed.add_field(
            name="지금 재생 중",
            value=make_track_link(state.current, DISCORD_EMBED_FIELD_LIMIT),
            inline=False,
        )

    if state.queue:
        lines = [
            make_queue_line(index, track)
            for index, track in enumerate(list(state.queue)[:10], start=1)
        ]
        if len(state.queue) > 10:
            lines.append(f"...and {len(state.queue) - 10} more")
        embed.add_field(name="다음 곡", value="\n".join(lines), inline=False)
    elif not state.current:
        embed.description = "대기열이 비어 있어요."

    return embed


def truncate_option_text(value: str, limit: int = 100) -> str:
    return truncate_text(value, limit)


def remove_queued_track(state: GuildMusicState, index: int) -> Track | None:
    if index < 0 or index >= len(state.queue):
        return None

    tracks = list(state.queue)
    removed = tracks.pop(index)
    state.queue = deque(tracks)
    return removed


def remove_queued_track_by_id(state: GuildMusicState, track_id: str) -> Track | None:
    for index, track in enumerate(state.queue):
        if track.track_id == track_id:
            return remove_queued_track(state, index)
    return None


class QueueRemoveSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        state = get_state(guild_id)
        options = [
            discord.SelectOption(
                label=truncate_option_text(f"{index}. {track.title}"),
                description=truncate_option_text(f"신청자: {track.requester}", 100),
                value=track.track_id,
            )
            for index, track in enumerate(list(state.queue)[:25], start=1)
        ]
        super().__init__(
            placeholder="삭제할 대기열 곡을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        state = get_state(self.guild_id)
        removed = remove_queued_track_by_id(state, self.values[0])
        if removed is None:
            await interaction.response.edit_message(
                content="이미 삭제되었거나 찾을 수 없는 곡이에요.",
                embed=make_queue_embed(state),
                view=QueueManageView(self.guild_id) if state.queue else None,
            )
            return

        if state.current:
            await send_player_panel(self.guild_id, state, state.current)

        await interaction.response.edit_message(
            content=f"대기열에서 `{removed.title}`을 삭제했어요.",
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
        )


class QueueManageView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        if get_state(guild_id).queue:
            self.add_item(QueueRemoveSelect(guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_same_voice_channel(interaction, get_state(self.guild_id))


class MusicControlView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    def get_state(self) -> GuildMusicState:
        return get_state(self.guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_same_voice_channel(interaction, self.get_state())

    async def edit_panel(self, interaction: discord.Interaction) -> None:
        state = self.get_state()
        if state.current is None:
            await interaction.response.edit_message(embed=discord.Embed(title="⏹️ 재생이 멈췄어요"), view=None)
            return

        await interaction.response.edit_message(
            embed=make_player_embed(state.current, state),
            view=MusicControlView(self.guild_id),
        )

    @discord.ui.button(label="재생/일시정지", emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        if state.voice is None:
            await interaction.response.send_message("봇이 음성 채널에 없어요.", ephemeral=True)
            return

        if state.voice.is_paused():
            state.voice.resume()
        elif state.voice.is_playing():
            state.voice.pause()
        else:
            await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)
            return

        await self.edit_panel(interaction)

    @discord.ui.button(label="스킵", emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
            state.skip_requested = True
            state.voice.stop()
            await interaction.response.send_message("다음 곡으로 넘어갈게요.", ephemeral=True)
            return

        await interaction.response.send_message("스킵할 곡이 없어요.", ephemeral=True)

    @discord.ui.button(label="정지", emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        stop_playback(state)
        await interaction.response.defer()
        await delete_player_panel(state)

    @discord.ui.button(label="반복", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def repeat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        state.repeat_one = not state.repeat_one
        await self.edit_panel(interaction)

    @discord.ui.button(label="셔플", emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        tracks = list(state.queue)
        random.shuffle(tracks)
        state.queue = deque(tracks)
        await self.edit_panel(interaction)

    @discord.ui.button(label="대기열 삭제", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        await interaction.response.send_message(
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
            ephemeral=True,
        )


def normalize_youtube_music_section(section: str) -> str:
    if section in YOUTUBE_MUSIC_SECTIONS:
        return section

    logger.warning("Invalid YOUTUBE_MUSIC_SECTION=%s. Falling back to songs.", section)
    return "songs"


def build_youtube_music_search_url(query: str, section: str | None = None) -> str:
    section = normalize_youtube_music_section(section or YOUTUBE_MUSIC_SECTION)
    encoded_query = urllib.parse.urlencode({"q": query})
    encoded_section = urllib.parse.quote_plus(section)
    return f"https://music.youtube.com/search?{encoded_query}#{encoded_section}"


def resolve_query(query: str, section: str | None = None) -> str:
    query = query.strip()
    parsed = urllib.parse.urlparse(query)

    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.lower().removeprefix("www.")
        if YOUTUBE_MUSIC_ONLY and host != "music.youtube.com":
            raise ValueError("YouTube Music 링크나 곡명만 사용할 수 있어요.")
        return query

    if YOUTUBE_MUSIC_ONLY:
        return build_youtube_music_search_url(query, section)

    return query


def is_url(value: str) -> bool:
    return urllib.parse.urlparse(value.strip()).scheme in {"http", "https"}


def build_youtube_search_fallback(query: str) -> str:
    return f"ytsearch1:{query} music"


async def extract_info_with_fallback(
    query: str,
    resolved_query: str,
    *,
    allow_fallback: bool,
) -> dict:
    try:
        info = await extract_ytdl_info(YTDL_OPTIONS, resolved_query, "YouTube Music search")
    except asyncio.TimeoutError:
        if not (allow_fallback and YOUTUBE_SEARCH_FALLBACK and not is_url(query)):
            raise ValueError(f"Timed out while searching for '{query}'.")

        fallback_query = build_youtube_search_fallback(query)
        logger.info("YouTube Music search timed out. Falling back to %s", fallback_query)
        return await extract_ytdl_info(YTDL_OPTIONS, fallback_query, "YouTube fallback search")

    if "entries" not in info:
        return info

    entries = [entry for entry in info["entries"] if entry]
    if entries:
        return entries[0]

    if allow_fallback and YOUTUBE_SEARCH_FALLBACK and not is_url(query):
        fallback_query = build_youtube_search_fallback(query)
        logger.info("YouTube Music search returned no results. Falling back to %s", fallback_query)
        fallback_info = await extract_ytdl_info(
            YTDL_OPTIONS, fallback_query, "YouTube fallback search"
        )
        fallback_entries = [entry for entry in fallback_info.get("entries", []) if entry]
        if fallback_entries:
            return fallback_entries[0]

    raise ValueError(f"No playable search results were found for '{query}'.")


def get_resolved_stream_url(info: dict) -> str | None:
    if info.get("_type") in {"url", "url_transparent"}:
        return None

    if not (info.get("formats") or info.get("requested_formats")):
        return None

    return info.get("url")


def get_thumbnail_url(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]

    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url")

    return None


def get_video_id(info: dict, url: str | None = None) -> str | None:
    video_id = info.get("id")
    if video_id and re.fullmatch(r"[\w-]{11}", video_id):
        return video_id

    if not url:
        return None

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    values = params.get("v")
    if values:
        return values[0]

    return None


def get_entry_url(info: dict, fallback_url: str) -> str:
    raw_url = info.get("webpage_url") or info.get("url") or fallback_url
    video_id = get_video_id(info, raw_url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme and raw_url:
        return f"https://www.youtube.com/watch?v={raw_url}"

    return raw_url


def normalize_track_key(track: Track) -> str:
    parsed = urllib.parse.urlparse(track.webpage_url)
    params = urllib.parse.parse_qs(parsed.query)
    video_id = params.get("v", [None])[0]
    if video_id:
        return video_id

    title = re.sub(r"\s+", " ", track.title).strip().lower()
    title = re.sub(r"\s*[\(\[].*?(official|mv|music video|lyrics?|audio|live).*?[\)\]]", "", title)
    return title


def make_track_from_info(
    info: dict,
    requester: str,
    fallback_url: str,
    requester_id: int | None = None,
) -> Track:
    source_url = get_entry_url(info, fallback_url)
    stream_url = get_resolved_stream_url(info)
    return Track(
        title=info.get("title") or "Untitled track",
        webpage_url=info.get("webpage_url") or source_url,
        requester=requester,
        source_url=source_url,
        requester_id=requester_id,
        duration=info.get("duration"),
        stream_url=stream_url,
        thumbnail_url=get_thumbnail_url(info),
        stream_resolved_at=time.monotonic() if stream_url else None,
    )


def is_search_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower().removeprefix("www.") == "music.youtube.com" and parsed.path == "/search"


def is_bulk_music_url(query: str) -> bool:
    parsed = urllib.parse.urlparse(query.strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower().removeprefix("www.")
    if host != "music.youtube.com":
        return False

    params = urllib.parse.parse_qs(parsed.query)
    return parsed.path == "/playlist" or ("list" in params and parsed.path != "/watch")


def parse_music_request(query: str) -> tuple[str, str | None, bool]:
    query = query.strip()
    lowered = query.lower()
    prefixes: dict[str, tuple[str, bool]] = {
        "album:": ("albums", True),
        "album ": ("albums", True),
        "playlist:": ("community playlists", True),
        "playlist ": ("community playlists", True),
        "list:": ("community playlists", True),
        "list ": ("community playlists", True),
    }

    for prefix, (section, bulk) in prefixes.items():
        if lowered.startswith(prefix):
            return query[len(prefix):].strip(), section, bulk

    return query, None, is_bulk_music_url(query)


def clamp_auto_count(count: int) -> int:
    return max(1, min(count, MAX_AUTO_TRACKS))


def parse_auto_request(query: str) -> tuple[str, int] | None:
    query = query.strip()
    match = re.match(r"^auto(?::|\s+)(.*)$", query, flags=re.IGNORECASE)
    if not match:
        return None

    rest = match.group(1).strip()
    count = DEFAULT_AUTO_TRACKS
    count_match = re.match(r"^(\d+)\s+(.+)$", rest)
    if count_match:
        count = clamp_auto_count(int(count_match.group(1)))
        rest = count_match.group(2).strip()

    if not rest:
        raise ValueError("auto: 뒤에 곡명이나 아티스트를 입력해 주세요.")

    return rest, count


async def resolve_track_stream(track: Track) -> None:
    stream_age = (
        time.monotonic() - track.stream_resolved_at
        if track.stream_resolved_at is not None
        else STREAM_URL_MAX_AGE_SECONDS
    )
    if track.stream_url and stream_age < STREAM_URL_MAX_AGE_SECONDS:
        return

    track.stream_url = None
    track.stream_resolved_at = None
    info = await extract_ytdl_info(YTDL_OPTIONS, track.source_url, "audio stream resolve")

    if "entries" in info:
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise ValueError("No playable search results were found.")
        info = entries[0]

    stream_url = get_resolved_stream_url(info)
    if not stream_url:
        raise ValueError("Could not resolve an audio stream for that query.")

    track.title = info.get("title") or track.title
    track.webpage_url = info.get("webpage_url") or track.webpage_url
    track.duration = info.get("duration") or track.duration
    track.stream_url = stream_url
    track.stream_resolved_at = time.monotonic()
    track.thumbnail_url = get_thumbnail_url(info) or track.thumbnail_url


async def extract_track(
    query: str,
    requester: str,
    section: str | None = None,
    requester_id: int | None = None,
) -> Track:
    resolved_query = resolve_query(query, section)
    info = await extract_info_with_fallback(
        query,
        resolved_query,
        allow_fallback=section in {None, "songs", "videos"},
    )

    track = make_track_from_info(info, requester, resolved_query, requester_id)
    await resolve_track_stream(track)
    return track


async def extract_tracks(
    query: str,
    requester: str,
    section: str | None = None,
    requester_id: int | None = None,
) -> list[Track]:
    resolved_query = resolve_query(query, section)
    info = await extract_ytdl_info(
        YTDL_PLAYLIST_OPTIONS, resolved_query, "playlist or album search"
    )

    if is_search_url(resolved_query):
        search_entries = [entry for entry in info.get("entries", []) if entry]
        if not search_entries:
            raise ValueError("No matching album or playlist was found.")

        first_result_url = get_entry_url(search_entries[0], resolved_query)
        info = await extract_ytdl_info(
            YTDL_PLAYLIST_OPTIONS, first_result_url, "playlist or album resolve"
        )

    entries = [entry for entry in info.get("entries", []) if entry]
    if not entries:
        return [await extract_track(query, requester, section, requester_id)]

    return [
        make_track_from_info(entry, requester, resolved_query, requester_id)
        for entry in entries[:MAX_BULK_TRACKS]
    ]


async def extract_auto_tracks(
    query: str,
    requester: str,
    count: int,
    requester_id: int | None = None,
) -> list[Track]:
    auto_count = clamp_auto_count(count)

    seed_query = resolve_query(query, "songs")
    seed_info = await extract_info_with_fallback(query, seed_query, allow_fallback=True)
    seed_track = make_track_from_info(seed_info, requester, seed_query, requester_id)
    seed_id = get_video_id(seed_info, seed_track.webpage_url)

    entries: list[dict] = []
    fallback_url = seed_query
    if seed_id:
        radio_url = f"https://www.youtube.com/watch?v={seed_id}&list=RD{seed_id}"
        fallback_url = radio_url
        try:
            radio_info = await extract_ytdl_info(
                YTDL_PLAYLIST_OPTIONS, radio_url, "YouTube radio mix"
            )
            entries = [entry for entry in radio_info.get("entries", []) if entry]
        except Exception:
            logger.exception("Failed to extract YouTube radio mix for %s", seed_id)

    if not entries:
        search_query = f"ytsearch{auto_count * 3}:{seed_track.title} radio mix"
        fallback_url = search_query
        info = await extract_ytdl_info(YTDL_OPTIONS, search_query, "auto fallback search")
        entries = [entry for entry in info.get("entries", []) if entry]

    tracks: list[Track] = []
    seen_keys: set[str] = set()

    for track in [seed_track]:
        key = normalize_track_key(track)
        seen_keys.add(key)
        tracks.append(track)
        if len(tracks) >= auto_count:
            return tracks

    for entry in entries:
        track = make_track_from_info(entry, requester, fallback_url, requester_id)
        if not get_video_id(entry, track.webpage_url):
            continue
        key = normalize_track_key(track)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        tracks.append(track)
        if len(tracks) >= auto_count:
            break

    if len(tracks) < auto_count and fallback_url.startswith("https://www.youtube.com/watch"):
        search_query = f"ytsearch{auto_count * 3}:{seed_track.title} radio mix"
        info = await extract_ytdl_info(
            YTDL_OPTIONS, search_query, "auto supplemental search"
        )
        for entry in [entry for entry in info.get("entries", []) if entry]:
            track = make_track_from_info(entry, requester, search_query, requester_id)
            key = normalize_track_key(track)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            tracks.append(track)
            if len(tracks) >= auto_count:
                break

    if not tracks:
        raise ValueError(f"관련 곡을 찾지 못했어요: {query}")

    return tracks


async def ensure_voice(interaction: discord.Interaction, state: GuildMusicState) -> bool:
    user = interaction.user
    voice_state = getattr(user, "voice", None)
    channel = getattr(voice_state, "channel", None)

    if channel is None:
        await interaction.followup.send("먼저 음성 채널에 들어가 주세요.", ephemeral=True)
        return False

    if state.voice and not state.voice.is_connected():
        stop_playback(state)
        state.voice = None

    if state.voice and state.voice.is_connected():
        if state.voice.channel != channel:
            if state.current or state.queue or state.voice.is_playing() or state.voice.is_paused():
                await interaction.followup.send(
                    f"봇이 이미 {state.voice.channel.mention}에서 재생 중이에요. "
                    "같은 음성 채널에 들어와 주세요.",
                    ephemeral=True,
                )
                return False
            await state.voice.move_to(channel)
        return True

    state.voice = await channel.connect()
    return True


async def ensure_voice_for_member(
    member: discord.Member,
    state: GuildMusicState,
) -> tuple[bool, str | None]:
    voice_state = getattr(member, "voice", None)
    channel = getattr(voice_state, "channel", None)

    if channel is None:
        return False, "먼저 음성 채널에 들어가 주세요."

    if state.voice and not state.voice.is_connected():
        stop_playback(state)
        state.voice = None

    if state.voice and state.voice.is_connected():
        if state.voice.channel != channel:
            if state.current or state.queue or state.voice.is_playing() or state.voice.is_paused():
                return (
                    False,
                    f"봇이 이미 {state.voice.channel.mention}에서 재생 중이에요. "
                    "같은 음성 채널에 들어와 주세요.",
                )
            await state.voice.move_to(channel)
        return True, None

    state.voice = await channel.connect()
    return True, None


async def ensure_same_voice_channel(
    interaction: discord.Interaction,
    state: GuildMusicState,
) -> bool:
    voice = state.voice
    member_channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
    if voice and voice.is_connected() and member_channel == voice.channel:
        return True

    message = "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    return False


def stop_playback(state: GuildMusicState) -> None:
    state.playback_generation += 1
    state.stop_requested = True
    state.queue.clear()
    state.current = None

    if state.advance_task and not state.advance_task.done():
        state.advance_task.cancel()
    state.advance_task = None

    if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
        state.voice.stop()


def schedule_play_next(
    guild_id: int,
    *,
    announce: bool = True,
) -> tuple[asyncio.Task[None], bool]:
    state = get_state(guild_id)
    if state.advance_task and not state.advance_task.done():
        return state.advance_task, False

    task = asyncio.create_task(play_next(guild_id, announce=announce))
    state.advance_task = task
    return task, True


async def enqueue_tracks(
    guild_id: int,
    text_channel: discord.abc.Messageable,
    requester: discord.abc.User,
    query: str,
    *,
    initial_response: discord.Message | None = None,
    interaction: discord.Interaction | None = None,
    bulk: bool | None = None,
    section: str | None = None,
    auto_count: int | None = None,
) -> bool:
    state = get_state(guild_id)
    state.announcement_channel = text_channel

    async def send_feedback(
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        private: bool = False,
    ) -> discord.Message | None:
        if initial_response:
            await initial_response.edit(content=content, embed=embed, view=view)
            if view is None or private:
                asyncio.create_task(
                    delete_message_later(initial_response, MUSIC_FEEDBACK_DELETE_SECONDS)
                )
            return initial_response

        if interaction:
            send_kwargs = {
                "content": content,
                "embed": embed,
                "ephemeral": private,
                "silent": is_silent_music_channel(interaction.channel),
                "wait": True,
            }
            if view is not None:
                send_kwargs["view"] = view

            try:
                return await interaction.followup.send(**send_kwargs)
            except discord.Forbidden:
                fallback_kwargs = {
                    "content": content,
                    "embed": embed,
                    "ephemeral": True,
                    "wait": True,
                }
                if view is not None:
                    fallback_kwargs["view"] = view
                return await interaction.followup.send(**fallback_kwargs)

        message = await text_channel.send(
            content=content,
            embed=embed,
            view=view,
            silent=is_silent_music_channel(text_channel),
        )
        if private:
            asyncio.create_task(delete_message_later(message, MUSIC_FEEDBACK_DELETE_SECONDS))
        return message

    try:
        auto_request = parse_auto_request(query)
        if auto_request:
            query, parsed_auto_count = auto_request
            auto_count = auto_count or parsed_auto_count
            bulk = True
        else:
            query, parsed_section, parsed_bulk = parse_music_request(query)
            section = section or parsed_section
            bulk = parsed_bulk if bulk is None else bulk

        tracks = (
            await extract_auto_tracks(query, requester.display_name, auto_count, requester.id)
            if auto_count is not None
            else (
                await extract_tracks(query, requester.display_name, section, requester.id)
                if bulk
                else [await extract_track(query, requester.display_name, section, requester.id)]
            )
        )
    except Exception as exc:
        logger.exception("Failed to extract track(s)")
        await send_feedback(content=f"곡을 찾지 못했어요: {exc}")
        return False

    if not tracks:
        await send_feedback(content="추가할 곡을 찾지 못했어요.")
        return False

    state.queue.extend(tracks)
    should_start = (
        bool(state.voice)
        and state.current is None
        and not state.voice.is_playing()
        and not state.voice.is_paused()
    )
    playback_task: asyncio.Task[None] | None = None
    started_playback = False
    if should_start:
        playback_task, started_playback = schedule_play_next(guild_id, announce=False)

    if started_playback and playback_task:
        await playback_task
        if state.current:
            message = await send_feedback(
                embed=make_player_embed(state.current, state),
                view=MusicControlView(guild_id),
            )
            if message:
                state.control_message = message
        else:
            await send_feedback(content="재생을 시작하지 못했어요. 로그를 확인해 주세요.")
        return state.current is not None

    if len(tracks) == 1:
        embed = make_track_embed(tracks[0], "Added to queue")
        embed.add_field(name="Position", value=str(len(state.queue)), inline=True)
    else:
        embed = make_bulk_embed(tracks, "Added playlist to queue")
        embed.add_field(name="Queue size", value=str(len(state.queue)), inline=True)

    await send_feedback(embed=embed, private=True)
    if state.current:
        await send_player_panel(guild_id, state, state.current)
    return True


async def send_player_panel(guild_id: int, state: GuildMusicState, track: Track) -> None:
    if not state.announcement_channel:
        return

    embed = make_player_embed(track, state)
    view = MusicControlView(guild_id)

    if state.control_message:
        try:
            await state.control_message.edit(embed=embed, view=view)
            return
        except (discord.Forbidden, discord.NotFound):
            state.control_message = None

    try:
        state.control_message = await state.announcement_channel.send(
            embed=embed,
            view=view,
            silent=is_silent_music_channel(state.announcement_channel),
        )
    except discord.Forbidden:
        logger.warning("Missing permission to send music control panel in guild %s", guild_id)


async def delete_player_panel(state: GuildMusicState) -> None:
    if state.control_message is None:
        return

    try:
        await state.control_message.delete()
    except discord.NotFound:
        pass
    finally:
        state.control_message = None


async def play_next(guild_id: int, announce: bool = True) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    generation = state.playback_generation

    try:
        if not ffmpeg_is_available():
            state.current = None
            state.queue.clear()
            await delete_player_panel(state)
            await notify_playback_error(
                state,
                "FFmpeg를 찾지 못해서 재생할 수 없어요. "
                "FFmpeg를 설치하거나 `.env`에 `FFMPEG_PATH`를 설정해 주세요.",
            )
            logger.error("FFmpeg executable was not found: %s", FFMPEG_EXECUTABLE)
            return

        while generation == state.playback_generation:
            async with state.lock:
                if generation != state.playback_generation:
                    return
                voice = state.voice
                if voice is None or not voice.is_connected():
                    state.current = None
                    should_delete_panel = True
                    track = None
                elif voice.is_playing() or voice.is_paused():
                    return
                elif not state.queue:
                    state.current = None
                    should_delete_panel = True
                    track = None
                else:
                    track = state.queue.popleft()
                    state.current = track
                    state.skip_requested = False
                    state.stop_requested = False
                    should_delete_panel = False

            if should_delete_panel:
                await delete_player_panel(state)
                return
            assert track is not None

            try:
                await resolve_track_stream(track)
                ffmpeg_source = discord.FFmpegPCMAudio(
                    track.stream_url,
                    executable=FFMPEG_EXECUTABLE,
                    **FFMPEG_OPTIONS,
                )
                source = discord.PCMVolumeTransformer(ffmpeg_source, volume=BOT_VOLUME)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to create FFmpeg source for %s", track.title)
                if state.current is track and generation == state.playback_generation:
                    state.current = None
                continue

            try:
                async with state.lock:
                    voice = state.voice
                    can_start = (
                        generation == state.playback_generation
                        and state.current is track
                        and voice is not None
                        and voice.is_connected()
                        and not voice.is_playing()
                        and not voice.is_paused()
                    )
                    if not can_start:
                        source.cleanup()
                        return

                    def after_playback(error: Exception | None) -> None:
                        if error:
                            logger.warning("Playback error: %s", error)

                        def advance() -> None:
                            if (
                                generation != state.playback_generation
                                or state.current is not track
                            ):
                                return

                            if state.repeat_one and not state.skip_requested and not state.stop_requested:
                                track.stream_url = None
                                track.stream_resolved_at = None
                                state.queue.appendleft(track)
                            state.current = None
                            schedule_play_next(guild_id)

                        bot.loop.call_soon_threadsafe(advance)

                    try:
                        voice.play(source, after=after_playback)
                    except Exception:
                        source.cleanup()
                        logger.exception("Failed to start playback for %s", track.title)
                        if state.current is track:
                            state.current = None
                        continue
            except asyncio.CancelledError:
                if not voice.is_playing():
                    source.cleanup()
                raise

            if announce and state.current is track:
                await send_player_panel(guild_id, state, track)
            return
    finally:
        if state.advance_task is current_task:
            state.advance_task = None


def guild_only_error() -> str:
    return "이 명령어는 디스코드 서버 안에서만 사용할 수 있어요."


@bot.event
async def on_ready() -> None:
    global commands_synced
    load_music_channel_config()
    logger.info("Logged in as %s", bot.user)
    if ffmpeg_is_available():
        logger.info("Using FFmpeg executable: %s", FFMPEG_EXECUTABLE)
    else:
        logger.error(
            "FFmpeg executable was not found. Set FFMPEG_PATH in .env or add ffmpeg to PATH."
        )

    if commands_synced:
        return

    if DEV_GUILD_ID:
        guild = discord.Object(id=int(DEV_GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.info("Synced %s command(s) to dev guild %s", len(synced), DEV_GUILD_ID)
    else:
        synced = await bot.tree.sync()
        logger.info("Synced %s global command(s)", len(synced))
    commands_synced = True


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return

    music_channel_id = get_music_channel_id(message.guild.id)
    if music_channel_id is None or message.channel.id != music_channel_id:
        return

    query = message.content.strip()
    if not query or query.startswith(("/", "!")):
        return

    if not isinstance(message.author, discord.Member):
        return

    state = get_state(message.guild.id)
    ok, error = await ensure_voice_for_member(message.author, state)
    if not ok:
        error_message = await message.reply(
            error,
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
        asyncio.create_task(delete_message_later(error_message, MUSIC_FEEDBACK_DELETE_SECONDS))
        await delete_music_request_message(message)
        return

    async with message.channel.typing():
        loading_message = await message.reply(
            "곡을 찾고 있어요...",
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
        await enqueue_tracks(
            message.guild.id,
            message.channel,
            message.author,
            query,
            initial_response=loading_message,
        )
        await delete_music_request_message(message)

    await bot.process_commands(message)


@bot.tree.command(
    name="setupmusic",
    description="Create or select a text channel for quick music requests.",
)
@app_commands.describe(channel="Existing channel to use. Leave empty to create one.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_music_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    selected_channel = channel
    if selected_channel is None:
        selected_channel = discord.utils.get(
            interaction.guild.text_channels,
            name=MUSIC_CHANNEL_NAME,
        )

    if selected_channel is None:
        selected_channel = await interaction.guild.create_text_channel(
            MUSIC_CHANNEL_NAME,
            reason="Music request channel setup",
        )

    set_music_channel(interaction.guild.id, selected_channel.id)
    await interaction.followup.send(
        f"{selected_channel.mention} 채널을 음악 신청 전용 채널로 설정했어요. "
        "이제 그 채널에 곡명이나 YouTube URL만 보내면 재생됩니다.",
        ephemeral=True,
    )


@setup_music_channel.error
async def setup_music_channel_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    async def send_error(content: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    if isinstance(error, app_commands.MissingPermissions):
        await send_error("이 설정은 채널 관리 권한이 있는 사람만 사용할 수 있어요.")
        return

    logger.exception("setupmusic failed", exc_info=error)
    await send_error("전용 채널을 설정하는 중 문제가 생겼어요.")


@bot.tree.command(name="join", description="Join your current voice channel.")
@app_commands.guild_only()
async def join(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if await ensure_voice(interaction, state):
        state.announcement_channel = interaction.channel
        await interaction.followup.send("음성 채널에 들어왔어요.", ephemeral=True)


@bot.tree.command(name="play", description="Play a YouTube Music URL or search YouTube Music.")
@app_commands.describe(query="YouTube Music URL or song search text")
@app_commands.guild_only()
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_voice(interaction, state):
        return

    await enqueue_tracks(
        interaction.guild_id,
        interaction.channel,
        interaction.user,
        query,
        interaction=interaction,
    )


@bot.tree.command(name="playalbum", description="Search YouTube Music albums and queue the first match.")
@app_commands.describe(query="Album search text or YouTube Music album URL")
@app_commands.guild_only()
async def play_album(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_voice(interaction, state):
        return

    await enqueue_tracks(
        interaction.guild_id,
        interaction.channel,
        interaction.user,
        query,
        interaction=interaction,
        bulk=True,
        section="albums",
    )


@bot.tree.command(name="playplaylist", description="Search YouTube Music playlists and queue the first match.")
@app_commands.describe(query="Playlist search text or YouTube Music playlist URL")
@app_commands.guild_only()
async def play_playlist(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_voice(interaction, state):
        return

    await enqueue_tracks(
        interaction.guild_id,
        interaction.channel,
        interaction.user,
        query,
        interaction=interaction,
        bulk=True,
        section="community playlists",
    )


@bot.tree.command(name="playauto", description="Queue related songs from a YouTube search.")
@app_commands.describe(
    query="Song, artist, or mood to start from",
    count="Number of related tracks to queue",
)
@app_commands.guild_only()
async def play_auto(
    interaction: discord.Interaction,
    query: str,
    count: app_commands.Range[int, 1, 25] = DEFAULT_AUTO_TRACKS,
) -> None:
    await interaction.response.defer()
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_voice(interaction, state):
        return

    await enqueue_tracks(
        interaction.guild_id,
        interaction.channel,
        interaction.user,
        query,
        interaction=interaction,
        bulk=True,
        auto_count=clamp_auto_count(count),
    )


@bot.tree.command(name="pause", description="Pause the current track.")
@app_commands.guild_only()
async def pause(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_playing():
        state.voice.pause()
        await interaction.response.send_message("일시정지했어요.", ephemeral=True)
        return

    await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="resume", description="Resume the paused track.")
@app_commands.guild_only()
async def resume(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_paused():
        state.voice.resume()
        await interaction.response.send_message("다시 재생할게요.", ephemeral=True)
        return

    await interaction.response.send_message("일시정지된 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="skip", description="Skip the current track.")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
        state.skip_requested = True
        state.voice.stop()
        await interaction.response.send_message("다음 곡으로 넘어갈게요.")
        return

    await interaction.response.send_message("스킵할 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
@app_commands.guild_only()
async def stop(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    stop_playback(state)

    await delete_player_panel(state)
    await interaction.response.send_message("재생을 멈추고 대기열을 비웠어요.")


@bot.tree.command(name="queue", description="Show the current music queue.")
@app_commands.guild_only()
async def show_queue(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    await interaction.response.send_message(
        embed=make_queue_embed(state),
        view=QueueManageView(interaction.guild_id) if state.queue else None,
        ephemeral=True,
    )


@bot.tree.command(name="remove", description="Remove a track from the queue by position.")
@app_commands.describe(position="Queue position to remove, starting from 1")
@app_commands.guild_only()
async def remove_from_queue(interaction: discord.Interaction, position: int) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    removed = remove_queued_track(state, position - 1)
    if removed is None:
        await interaction.response.send_message("그 번호의 대기열 곡을 찾지 못했어요.", ephemeral=True)
        return

    if state.current:
        await send_player_panel(interaction.guild_id, state, state.current)

    await interaction.response.send_message(
        f"대기열에서 `{removed.title}`을 삭제했어요.",
        ephemeral=True,
    )


@bot.tree.command(name="nowplaying", description="Show the current track.")
@app_commands.guild_only()
async def now_playing(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if state.current:
        await interaction.response.send_message(
            embed=make_player_embed(state.current, state),
            view=MusicControlView(interaction.guild_id),
        )
        return

    await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="leave", description="Disconnect from voice and clear the queue.")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    stop_playback(state)

    if state.voice and state.voice.is_connected():
        await delete_player_panel(state)
        await state.voice.disconnect()
        state.voice = None
        await interaction.response.send_message("음성 채널에서 나왔어요.")
        return

    await interaction.response.send_message("이미 음성 채널에 없어요.", ephemeral=True)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Put it in .env or your environment.")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
