from __future__ import annotations

import io

import discord

from music_models import GuildMusicState, Track


DISCORD_EMBED_FIELD_LIMIT = 1024
PLAYING_PANEL_TITLE = "💿 지금 재생 중"
IDLE_PANEL_TITLE = "🎵 재생 대기 중"
CONTROL_PANEL_TITLES = frozenset({PLAYING_PANEL_TITLE, IDLE_PANEL_TITLE})
LYRICS_INLINE_LIMIT = 3900


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
