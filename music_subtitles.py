from __future__ import annotations

import html
import json
import re

from music_models import Track


class YouTubeSubtitleError(RuntimeError):
    pass


def normalize_subtitle_text(value: str) -> str:
    return html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_json3_lyrics(payload: str) -> str | None:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.") from error
    if not isinstance(document, dict):
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.")

    lines: list[str] = []
    for event in document.get("events") or []:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs") or []
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in segments
            if isinstance(segment, dict)
        )
        for line in normalize_subtitle_text(text).splitlines():
            line = line.strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


VTT_TIMESTAMP_LINE_RE = re.compile(
    r"^(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


def extract_vtt_lyrics(payload: str) -> str | None:
    lines: list[str] = []
    skip_block = False
    for raw_line in normalize_subtitle_text(payload).splitlines():
        line = raw_line.strip()
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if not line:
            skip_block = False
            continue
        if skip_block or line == "WEBVTT" or VTT_TIMESTAMP_LINE_RE.match(line):
            continue
        if line.isdigit():
            continue
        line = normalize_subtitle_text(VTT_TAG_RE.sub("", line))
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


def get_subtitle_candidates(
    subtitles: dict[str, list[dict]],
) -> list[tuple[str, str, str, int]]:
    candidates: list[tuple[str, str, str, int]] = []
    format_scores = {"json3": 30, "vtt": 20}
    for language, formats in subtitles.items():
        if not isinstance(formats, list):
            continue
        for subtitle_format in formats:
            if not isinstance(subtitle_format, dict):
                continue
            extension = str(subtitle_format.get("ext") or "").casefold()
            url = subtitle_format.get("url")
            if extension not in format_scores or not isinstance(url, str) or not url:
                continue
            candidates.append(
                (str(language), extension, url, format_scores[extension])
            )
    return candidates


def get_manual_subtitle_candidates(track: Track) -> list[tuple[str, str, str, int]]:
    return get_subtitle_candidates(track.manual_subtitles)


def select_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    preferred_language = (track.subtitle_language or "").casefold()
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold()
        language_score = 0
        if preferred_language and (
            language_key == preferred_language
            or language_key.split("-", 1)[0] == preferred_language.split("-", 1)[0]
        ):
            language_score += 100
        if language_key.endswith("-orig"):
            language_score += 50
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url


def select_korean_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold().replace("_", "-")
        language_parts = language_key.split("-")
        if not language_parts or language_parts[0] != "ko":
            continue
        language_score = 20 if language_key in {"ko", "ko-kr"} else 0
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url
