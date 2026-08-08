from __future__ import annotations

from music_models import Track


DISCORD_EMBED_FIELD_LIMIT = 1024


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
