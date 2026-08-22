from __future__ import annotations

import asyncio
import io

import discord

from music_config import (
    MAX_BULK_TRACKS,
    MUSIC_CHANNEL_DELETE_REQUESTS,
    MUSIC_CHANNEL_SILENT,
    get_music_channel_id,
    logger,
)
from music_models import GuildMusicState, RecentPlaybackEntry, Track


DISCORD_EMBED_FIELD_LIMIT = 1024
PLAYING_PANEL_TITLE = "💿 지금 재생 중"
IDLE_PANEL_TITLE = "🎵 재생 대기 중"
CONTROL_PANEL_TITLES = frozenset({PLAYING_PANEL_TITLE, IDLE_PANEL_TITLE})
LYRICS_INLINE_LIMIT = 3900
RECENT_PLAYBACKS_PER_FIELD = 10
RECENT_PLAYBACK_LINK_LIMIT = 72


def is_silent_music_channel(channel: discord.abc.Messageable | None) -> bool:
    if not MUSIC_CHANNEL_SILENT or channel is None:
        return False

    guild = getattr(channel, "guild", None)
    channel_id = getattr(channel, "id", None)
    if guild is None or channel_id is None:
        return False

    return get_music_channel_id(guild.id) == channel_id


def log_discord_http_error(action: str, error: discord.HTTPException) -> None:
    logger.warning(
        "Discord API failed while %s: HTTP %s (code %s)",
        action,
        getattr(error, "status", "unknown"),
        getattr(error, "code", "unknown"),
    )


async def send_music_request_reply(
    message: discord.Message,
    content: str,
) -> discord.Message | None:
    try:
        return await message.reply(
            content,
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
    except discord.HTTPException as error:
        log_discord_http_error("sending a music request reply", error)
        return None


async def delete_music_request_message(message: discord.Message) -> None:
    if not MUSIC_CHANNEL_DELETE_REQUESTS:
        return

    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting a music request", error)


async def delete_message_later(
    message: discord.Message,
    delay_seconds: float,
) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting temporary music feedback", error)


async def delete_interaction_response_later(
    interaction: discord.Interaction,
    delay_seconds: float,
) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error(
            "deleting a temporary interaction response",
            error,
        )


async def notify_playback_error(state: GuildMusicState, content: str) -> None:
    if not state.announcement_channel:
        return

    try:
        await state.announcement_channel.send(
            content,
            silent=is_silent_music_channel(state.announcement_channel),
        )
    except discord.HTTPException as error:
        log_discord_http_error("sending a playback error message", error)


async def delete_private_interaction_message(
    message: discord.WebhookMessage | discord.InteractionMessage,
) -> None:
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting a private interaction message", error)


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


def single_line(value: str) -> str:
    return " ".join(value.split())


def truncate_text(value: str, limit: int) -> str:
    value = single_line(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def make_track_link(track: Track, limit: int = DISCORD_EMBED_FIELD_LIMIT) -> str:
    title = truncate_text(track.title, 120)
    if not track.webpage_url:
        return title
    value = f"[{title}]({track.webpage_url})"
    if len(value) <= limit:
        return value
    return truncate_text(track.title, limit)


def make_queue_line(index: int, track: Track) -> str:
    return f"{index}. {truncate_text(track.title, 72)} - {format_duration(track.duration)}"


def make_recent_playback_link(entry: RecentPlaybackEntry) -> str:
    title = single_line(entry.title) or "알 수 없는 곡"
    if entry.webpage_url:
        title_limit = RECENT_PLAYBACK_LINK_LIMIT - len(entry.webpage_url) - 4
        if title_limit >= 8:
            return f"[{truncate_text(title, title_limit)}]({entry.webpage_url})"
    return truncate_text(title, RECENT_PLAYBACK_LINK_LIMIT)


def make_recent_playback_line(
    index: int,
    entry: RecentPlaybackEntry,
) -> str:
    return (
        f"{index}. {make_recent_playback_link(entry)} · "
        f"<t:{int(entry.played_at)}:R>"
    )


def truncate_option_text(value: str, limit: int = 100) -> str:
    return truncate_text(value, limit)


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
    autoplay_text = "켜짐" if state.autoplay_enabled else "꺼짐"
    embed = discord.Embed(
        title=PLAYING_PANEL_TITLE,
        description=f"🎧 {requester_label(track)}님이 신청한 곡이에요!",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="YouTube",
        value=make_track_link(track, DISCORD_EMBED_FIELD_LIMIT),
        inline=False,
    )
    embed.add_field(name="길이", value=format_duration(track.duration), inline=True)
    embed.add_field(name="대기열", value=f"{queue_count}곡", inline=True)
    embed.add_field(name="반복", value=repeat_text, inline=True)
    embed.add_field(name="자동재생", value=autoplay_text, inline=True)
    if state.queue:
        preview = []
        for index, queued in enumerate(list(state.queue)[:5], start=1):
            preview.append(make_queue_line(index, queued))
        if len(state.queue) > 5:
            preview.append(f"...and {len(state.queue) - 5} more")
        embed.add_field(name="다음 곡", value="\n".join(preview), inline=False)
    if track.thumbnail_url:
        embed.set_image(url=track.thumbnail_url)
    return embed


def make_idle_player_embed() -> discord.Embed:
    return discord.Embed(
        title=IDLE_PANEL_TITLE,
        description=(
            "음성 채널에 들어간 뒤 아래 형식으로 메시지를 보내 주세요.\n\n"
            "`곡명` 또는 `YouTube URL`\n"
            "`album: 앨범명`\n"
            "`playlist: 플레이리스트명`\n"
            "`auto: 곡명`, `auto12: 곡명` 또는 `auto 12: 곡명`\n\n"
            "자동재생은 아래 버튼으로 켜고 끌 수 있어요."
        ),
        color=discord.Color.blurple(),
    )


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


def make_recent_playback_embed(
    entries: tuple[RecentPlaybackEntry, ...],
) -> discord.Embed:
    embed = discord.Embed(title="🕘 최근 재생곡", color=discord.Color.blurple())
    if not entries:
        embed.description = "현재 실행 중 기록된 최근 재생곡이 없어요."
        return embed

    embed.description = (
        "자동재생 중복 방지 기간에 실제 재생을 시작한 순서예요. "
        "같은 곡도 재생할 때마다 표시되며, 봇을 재시작하면 초기화돼요."
    )
    visible_entries = entries[:50]
    for offset in range(0, len(visible_entries), RECENT_PLAYBACKS_PER_FIELD):
        group = visible_entries[offset : offset + RECENT_PLAYBACKS_PER_FIELD]
        first_index = offset + 1
        last_index = offset + len(group)
        embed.add_field(
            name=f"{first_index}–{last_index}",
            value="\n".join(
                make_recent_playback_line(index, entry)
                for index, entry in enumerate(group, start=first_index)
            ),
            inline=False,
        )
    return embed


def make_bulk_embed(tracks: list[Track], title: str) -> discord.Embed:
    embed = discord.Embed(title=title)
    preview = [
        f"{index}. {make_track_link(track, DISCORD_EMBED_FIELD_LIMIT - 8)}"
        for index, track in enumerate(tracks[:10], start=1)
    ]
    if len(tracks) > 10:
        preview.append(f"...and {len(tracks) - 10} more")

    embed.description = "\n".join(preview)
    embed.add_field(name="Added", value=str(len(tracks)), inline=True)
    embed.add_field(name="Limit", value=str(MAX_BULK_TRACKS), inline=True)
    return embed


def describe_queue_selection(state: GuildMusicState, track_id: str | None) -> str:
    if track_id is None:
        return "선택 안 함"

    for index, track in enumerate(state.queue, start=1):
        if track.track_id == track_id:
            return f"{index}. {truncate_text(track.title, 72)}"
    return "대기열에서 찾을 수 없음"


def make_lyrics_embed(track: Track, description: str) -> discord.Embed:
    song_title = track.song_name or track.title
    embed = discord.Embed(
        title=f"가사 · {truncate_text(song_title, 220)}",
        description=description,
        color=discord.Color.blurple(),
    )
    artist = track.artist or track.uploader
    if artist:
        embed.set_author(name=truncate_text(artist, 200))

    source = track.lyrics_source or "LRCLIB → YouTube 수동 자막"
    embed.set_footer(text=f"{source} · 원문 가사")
    return embed


def make_lyrics_variant_embed(
    track: Track,
    label: str,
    description: str,
    source: str,
    source_url: str | None = None,
) -> discord.Embed:
    song_title = track.song_name or track.title
    embed = discord.Embed(
        title=f"{label} · {truncate_text(song_title, 220)}",
        description=description,
        color=discord.Color.blurple(),
    )
    artist = track.artist or track.uploader
    if artist:
        embed.set_author(name=truncate_text(artist, 200))
    if source_url:
        embed.url = source_url
    embed.set_footer(text=source)
    return embed


def make_lyrics_file(lyrics: str, filename: str = "lyrics.txt") -> discord.File:
    return discord.File(
        io.BytesIO(lyrics.encode("utf-8")),
        filename=filename,
    )
