from __future__ import annotations

import io

import discord

from music_models import Track
from music_text import truncate_text


LYRICS_INLINE_LIMIT = 3900


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
