from __future__ import annotations

import re
import unicodedata
import urllib.parse

from music_config import YOUTUBE_SEARCH_CANDIDATES, logger
from music_discord_display import format_duration
from music_request_parsing import (
    YOUTUBE_HOSTS,
    build_youtube_playlist_search_url,
)


BRACKETED_TITLE_PART_RE = re.compile(
    r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］|「[^」]*」|『[^』]*』"
)
LEADING_BRACKETED_TITLE_PART_RE = re.compile(
    r"^\s*(?:\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］)\s*"
)
TRAILING_BRACKETED_TITLE_PART_RE = re.compile(
    r"\s*(?:\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］)\s*$"
)
VERSION_MARKER_RE = re.compile(
    r"\b(?:live|remix|cover|acoustic|instrumental|demo|version|edit|sped\s*up|slowed(?:\s*down)?|nightcore)\b"
    r"|라이브|리믹스|커버|어쿠스틱|인스트루멘털|데모"
    r"|ライブ|リミックス|カバー|アコースティック|インスト",
    flags=re.IGNORECASE,
)
NON_SONG_LABEL_RE = re.compile(
    r"\b(?:official|music\s*video|m\s*/?\s*v|audio|lyric(?:s|\s*video)?|visuali[sz]er|4k|hd|ost|original\s*soundtrack|theme\s*song)\b"
    r"|공식|뮤직비디오|가사|음원|오디오|주제가"
    r"|公式|ミュージックビデオ|オーディオ|歌詞|音源|主題歌",
    flags=re.IGNORECASE,
)
NON_SONG_SUFFIX_RE = re.compile(
    r"(?:\s*[-|:]\s*|\s+)"
    r"(?:official\s*(?:music\s*)?(?:video|mv|audio)|music\s*video|m\s*/?\s*v|official\s*audio|lyric(?:s|\s*video)?|visuali[sz]er|4k|hd|ost|original\s*soundtrack|theme\s*song|공식\s*(?:뮤직비디오|음원|오디오)?|뮤직비디오|가사|음원|오디오|公式\s*(?:mv|ミュージックビデオ|オーディオ|音源)?|ミュージックビデオ|オーディオ|歌詞|音源|主題歌)\s*$",
    flags=re.IGNORECASE,
)
ARTIST_CHANNEL_SUFFIX_RE = re.compile(
    r"(?:\s*-\s*topic|\s*official(?:\s+channel)?|vevo|\s*공식(?:\s*채널)?|\s*公式(?:チャンネル)?)$",
    flags=re.IGNORECASE,
)


def clean_track_title_preserving_case(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)

    def replace_bracketed_part(match: re.Match[str]) -> str:
        part = match.group(0)
        if VERSION_MARKER_RE.search(part):
            return part
        if NON_SONG_LABEL_RE.search(part):
            return " "
        return part

    value = BRACKETED_TITLE_PART_RE.sub(replace_bracketed_part, value)
    previous = None
    while previous != value:
        previous = value
        value = NON_SONG_SUFFIX_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_track_title(value: str) -> str:
    return clean_track_title_preserving_case(value).casefold()


def strip_edge_title_tags(value: str) -> str:
    value = value.strip()
    previous = None
    while value and previous != value:
        previous = value
        value = LEADING_BRACKETED_TITLE_PART_RE.sub("", value)
        value = TRAILING_BRACKETED_TITLE_PART_RE.sub("", value)
    return value.strip()


def normalize_identity_component(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()


def normalize_artist_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = ARTIST_CHANNEL_SUFFIX_RE.sub("", value)
    return normalize_identity_component(value)


FULL_VERSION_SEARCH_RE = re.compile(
    r"\b(?:full(?:\s*(?:ver(?:sion)?|size|song))?|complete\s*version|long\s*version)\b"
    r"|フル(?:サイズ|バージョン|ver\.?)?|完全版|完整版"
    r"|풀\s*버전|풀버전|완곡",
    flags=re.IGNORECASE,
)
SHORT_VERSION_SEARCH_RE = re.compile(
    r"\b(?:short(?:\s*ver(?:sion)?)?|tv\s*(?:size|ver(?:sion)?)"
    r"|anime\s*(?:size|ver(?:sion)?)|game\s*(?:size|ver(?:sion)?)"
    r"|preview|teaser|sample|one\s*chorus|1\s*chorus)\b"
    r"|ショート(?:ver\.?)?|TVサイズ|テレビサイズ|アニメサイズ"
    r"|ゲームサイズ|ワンコーラス|試聴(?:版)?"
    r"|숏\s*버전|숏버전|TV\s*판|애니\s*버전|게임\s*버전"
    r"|미리듣기|1절\s*버전",
    flags=re.IGNORECASE,
)
GAME_VIDEO_SEARCH_RE = re.compile(
    r"\b(?:2d|3d)\s*m\s*/?\s*v\b|\bgame\s*(?:mv|movie|play)\b"
    r"|\b(?:op|ed)\s*(?:movie|animation)\b|\bcreditless\b"
    r"|ノンクレジット|ゲーム(?:MV|映像)|プレイ動画|譜面"
    r"|오프닝\s*영상|엔딩\s*영상|게임\s*(?:MV|영상)|플레이\s*영상",
    flags=re.IGNORECASE,
)
ALTERNATE_VERSION_SEARCH_RE = re.compile(
    r"\b(?:cover|remix|live|instrumental|karaoke|acoustic|sped\s*up"
    r"|off\s*vocal|slowed(?:\s*down)?|nightcore|solo)\b"
    r"|ver(?:sion)?\.?(?=\s|[)\]}>】」』）]|$)"
    r"|カバー|歌ってみた|リミックス|ライブ|インスト|カラオケ"
    r"|オフボーカル|アコースティック|ソロ"
    r"|커버|리믹스|라이브|연주|노래방|오프\s*보컬|솔로",
    flags=re.IGNORECASE,
)
LONG_FORM_SEARCH_RE = re.compile(
    r"\b(?:extended|loop|hour|medley|compilation|playlist)\b"
    r"|耐久|作業用|メドレー|모음|메들리|반복",
    flags=re.IGNORECASE,
)
OFFICIAL_MEDIA_SEARCH_RE = re.compile(
    r"\b(?:official|music\s*video|m\s*/?\s*v|official\s*audio"
    r"|lyric(?:s|\s*video)?)\b"
    r"|公式|ミュージックビデオ|オーディオ|歌詞"
    r"|공식|뮤직비디오|오디오|가사",
    flags=re.IGNORECASE,
)
OFFICIAL_VIDEO_SEARCH_RE = re.compile(
    r"\bofficial\s*(?:music\s*)?(?:video|m\s*/?\s*v)\b"
    r"|公式\s*(?:ミュージックビデオ|m\s*/?\s*v)"
    r"|공식\s*(?:뮤직비디오|m\s*/?\s*v)",
    flags=re.IGNORECASE,
)
OFFICIAL_AUDIO_SEARCH_RE = re.compile(
    r"\bofficial\s*audio\b|公式\s*(?:オーディオ|音源)|공식\s*(?:오디오|음원)",
    flags=re.IGNORECASE,
)
OFFICIAL_CHANNEL_RE = re.compile(
    r"\bofficial\b|\bvevo\b|(?:^|\s)-\s*topic$|公式|공식",
    flags=re.IGNORECASE,
)
YOUTUBE_SEARCH_NOISE_TOKENS = frozenset(
    {
        "music",
        "song",
        "official",
        "audio",
        "video",
        "lyrics",
        "lyric",
        "mv",
        "노래",
        "음악",
        "가사",
        "공식",
    }
)


def should_use_youtube_music_search(query: str) -> bool:
    return not any(
        pattern.search(query)
        for pattern in (
            SHORT_VERSION_SEARCH_RE,
            GAME_VIDEO_SEARCH_RE,
            ALTERNATE_VERSION_SEARCH_RE,
            LONG_FORM_SEARCH_RE,
        )
    )


def get_youtube_music_artist_names(result: dict) -> list[str]:
    artists = result.get("artists")
    if isinstance(artists, list):
        names = [
            str(artist.get("name")).strip()
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ]
        if names:
            return names

    artist = result.get("artist")
    if isinstance(artist, str) and artist.strip():
        return [artist.strip()]
    return []


def youtube_music_result_to_entry(result: dict) -> dict | None:
    video_id = result.get("videoId")
    title = result.get("title")
    if (
        result.get("resultType") != "song"
        or not isinstance(video_id, str)
        or not re.fullmatch(r"[\w-]{11}", video_id)
        or not isinstance(title, str)
        or not title.strip()
    ):
        return None

    artists = get_youtube_music_artist_names(result)
    artist = ", ".join(artists) or None
    album = result.get("album")
    album_name = album.get("name") if isinstance(album, dict) else None
    thumbnails = result.get("thumbnails")
    thumbnail = None
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and item.get("url"):
                thumbnail = item["url"]
                break

    webpage_url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id,
        "url": webpage_url,
        "webpage_url": webpage_url,
        "title": title.strip(),
        "track": title.strip(),
        "artist": artist,
        "creator": artist,
        "channel": artist,
        "album": album_name,
        "duration": result.get("duration_seconds"),
        "thumbnail": thumbnail,
        "_music_bot_youtube_music": True,
    }


def youtube_music_entries_are_ambiguous(
    query: str,
    entries: list[dict],
) -> bool:
    normalized_query = normalize_identity_component(clean_track_title(query))
    if not normalized_query:
        return False

    exact_title_artists = {
        normalize_artist_name(str(entry.get("artist") or entry.get("creator") or ""))
        for entry in entries
        if normalize_identity_component(
            clean_track_title(str(entry.get("track") or entry.get("title") or ""))
        )
        == normalized_query
        and (entry.get("artist") or entry.get("creator"))
    }
    return len(exact_title_artists) > 1


def get_youtube_music_artist_hint(query: str, results: list[dict]) -> str | None:
    song_entries = [
        entry
        for result in results
        if (entry := youtube_music_result_to_entry(result)) is not None
    ]
    if youtube_music_entries_are_ambiguous(query, song_entries):
        return None

    normalized_query = normalize_identity_component(query)
    for index, result in enumerate(results[:3]):
        if result.get("resultType") not in {"album", "song"}:
            continue
        if index > 0 and str(result.get("category") or "").casefold() != "top result":
            continue

        artists = get_youtube_music_artist_names(result)
        if not artists:
            continue
        artist = artists[0]
        normalized_artist = normalize_artist_name(artist)
        if (
            not normalized_artist
            or normalized_artist in normalized_query
            or len(artist) > 120
        ):
            return None
        return artist
    return None


def get_youtube_search_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return {
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if len(token) >= 2 and token not in YOUTUBE_SEARCH_NOISE_TOKENS
    }


def get_search_result_duration(entry: dict) -> float | None:
    duration = entry.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    return None


def infer_youtube_search_song_title(
    entry: dict,
    preferred_artist: str | None = None,
) -> str | None:
    track = entry.get("track")
    if isinstance(track, str) and track.strip():
        return clean_track_title_preserving_case(track)

    raw_title = entry.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        return None

    quoted_match = re.search(r"[「『](?P<title>[^」』]+)[」』]", raw_title)
    if quoted_match:
        candidate = quoted_match.group("title")
    else:
        slash_parts = re.split(r"\s*/\s*", raw_title, maxsplit=1)
        if len(slash_parts) == 2:
            candidate = slash_parts[0]
        else:
            candidate = raw_title
            dash_parts = re.split(
                r"\s+(?:-|–|—|\|)\s+",
                raw_title,
                maxsplit=1,
            )
            if len(dash_parts) == 2 and preferred_artist:
                normalized_artist = normalize_artist_name(preferred_artist)
                if normalize_artist_name(dash_parts[0]) == normalized_artist:
                    candidate = dash_parts[1]
                elif normalize_artist_name(dash_parts[1]) == normalized_artist:
                    candidate = dash_parts[0]

    candidate = strip_edge_title_tags(candidate)
    return clean_track_title_preserving_case(candidate) or None


def is_likely_official_youtube_upload(entry: dict) -> bool:
    raw_title = str(entry.get("title") or "")
    channel = str(entry.get("channel") or entry.get("uploader") or "")
    if not channel:
        return False
    if OFFICIAL_CHANNEL_RE.search(channel):
        return True

    title_parts = re.split(
        r"\s+(?:-|–|—|\|)\s+",
        raw_title,
        maxsplit=1,
    )
    if len(title_parts) != 2:
        quoted_match = re.match(r"^\s*(?P<artist>.+?)[「『]", raw_title)
        if quoted_match is None:
            return False
        title_artist = quoted_match.group("artist")
    else:
        title_artist = title_parts[0]

    normalized_title_artist = normalize_artist_name(title_artist)
    normalized_channel = normalize_artist_name(channel)
    if not normalized_title_artist or not normalized_channel:
        return False
    if normalized_title_artist == normalized_channel:
        return True
    return (
        min(len(normalized_title_artist), len(normalized_channel)) >= 4
        and (
            normalized_title_artist in normalized_channel
            or normalized_channel in normalized_title_artist
        )
    )


def score_youtube_search_result(
    entry: dict,
    query: str,
    result_index: int,
    preferred_artist: str | None = None,
    preferred_title: str | None = None,
) -> int:
    title = str(entry.get("title") or "")
    artist = str(entry.get("artist") or entry.get("creator") or "")
    uploader = str(entry.get("channel") or entry.get("uploader") or "")
    searchable = " ".join((title, artist, uploader)).strip()
    normalized_query = normalize_identity_component(query)
    normalized_searchable = normalize_identity_component(searchable)
    query_tokens = get_youtube_search_tokens(query)
    candidate_tokens = get_youtube_search_tokens(searchable)

    score = max(0, 30 - result_index * 3)
    if normalized_query and normalized_query in normalized_searchable:
        score += 100
    if query_tokens:
        overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
        score += round(overlap * 80)

    query_requests_short = bool(SHORT_VERSION_SEARCH_RE.search(query))
    query_requests_game_video = bool(GAME_VIDEO_SEARCH_RE.search(query))
    query_requests_alternate = bool(ALTERNATE_VERSION_SEARCH_RE.search(query))
    query_requests_long_form = bool(LONG_FORM_SEARCH_RE.search(query))
    query_requests_official_video = bool(OFFICIAL_VIDEO_SEARCH_RE.search(query))
    query_requests_official_audio = bool(OFFICIAL_AUDIO_SEARCH_RE.search(query))
    query_requests_short_form = query_requests_short or query_requests_game_video

    duration = get_search_result_duration(entry)
    if duration is None:
        score -= 5
    elif duration < 45:
        score -= 140
    elif duration < 90:
        score += -20 if query_requests_short_form else -90
    elif duration < 150:
        score += 15 if query_requests_short_form else -50
    elif duration < 180:
        score += 10 if query_requests_short_form else -20
    elif duration <= 420:
        score += 30
    elif duration <= 600:
        score += 10
    elif duration > 900:
        score -= 90
    else:
        score -= 20

    if FULL_VERSION_SEARCH_RE.search(searchable):
        score += 35
    if SHORT_VERSION_SEARCH_RE.search(searchable):
        score += 70 if query_requests_short else -120
    if GAME_VIDEO_SEARCH_RE.search(searchable):
        if query_requests_game_video:
            score += 50
        elif duration is None or duration < 210:
            score -= 70
        else:
            score -= 20
    if (
        ALTERNATE_VERSION_SEARCH_RE.search(searchable)
        and not FULL_VERSION_SEARCH_RE.search(searchable)
    ):
        score += 40 if query_requests_alternate else -45
    if LONG_FORM_SEARCH_RE.search(searchable):
        score += 40 if query_requests_long_form else -80
    if OFFICIAL_MEDIA_SEARCH_RE.search(searchable) and (
        duration is None or 150 <= duration <= 600
    ):
        score += 8
    if OFFICIAL_VIDEO_SEARCH_RE.search(searchable):
        score += 55 if query_requests_official_video else 18
    if OFFICIAL_AUDIO_SEARCH_RE.search(searchable):
        score += 55 if query_requests_official_audio else 6
    if is_likely_official_youtube_upload(entry):
        score += 40
    if preferred_artist:
        candidate_artist = artist or uploader
        if candidate_artist:
            normalized_preferred_artist = normalize_artist_name(preferred_artist)
            normalized_candidate_artist = normalize_artist_name(candidate_artist)
            if normalized_candidate_artist == normalized_preferred_artist:
                score += 60
    if preferred_title:
        normalized_preferred_title = normalize_identity_component(preferred_title)
        normalized_raw_title = normalize_identity_component(title)
        inferred_title = infer_youtube_search_song_title(
            entry,
            preferred_artist,
        )
        normalized_inferred_title = (
            normalize_identity_component(inferred_title)
            if inferred_title
            else ""
        )
        if normalized_raw_title == normalized_preferred_title:
            score += 120
        elif normalized_inferred_title == normalized_preferred_title:
            score += 50
        elif (
            normalized_preferred_title
            and normalized_preferred_title in normalized_raw_title
        ):
            score += 25

    if entry.get("is_live") or entry.get("live_status") in {
        "is_live",
        "is_upcoming",
        "post_live",
    }:
        score -= 200
    return score


def select_youtube_music_song_result(query: str, results: list[dict]) -> dict | None:
    entries = [
        entry
        for result in results
        if (entry := youtube_music_result_to_entry(result)) is not None
    ]
    if not entries:
        return None
    if youtube_music_entries_are_ambiguous(query, entries):
        logger.info(
            "YouTube Music returned multiple artists for title-only query %s; "
            "using YouTube ranking instead",
            query,
        )
        return None

    selected = select_youtube_search_result(query, entries)
    logger.info(
        "YouTube Music selected catalog song for %s: %s (%s)",
        query,
        selected.get("title"),
        selected.get("id"),
    )
    return selected


def build_youtube_search_query(
    query: str,
    artist_hint: str | None = None,
) -> str:
    search_text = query
    if artist_hint:
        search_text = f"{query} {artist_hint}"
    return f"ytsearch{YOUTUBE_SEARCH_CANDIDATES}:{search_text}"


def select_youtube_search_result(
    query: str,
    entries: list[dict],
    preferred_artist: str | None = None,
    preferred_title: str | None = None,
) -> dict:
    candidates = [
        entry
        for entry in entries
        if isinstance(entry, dict) and (entry.get("id") or entry.get("url"))
    ]
    if not candidates:
        raise ValueError(f"No playable search results were found for '{query}'.")

    ranked = [
        (
            score_youtube_search_result(
                entry,
                query,
                index,
                preferred_artist,
                preferred_title,
            ),
            -index,
            entry,
        )
        for index, entry in enumerate(candidates)
    ]
    score, negative_index, selected = max(
        ranked,
        key=lambda candidate: candidate[:2],
    )
    logger.info(
        "YouTube search selected result %s/%s for %s: %s (%s, score %s)",
        -negative_index + 1,
        len(candidates),
        query,
        selected.get("title") or "Untitled track",
        format_duration(selected.get("duration")),
        score,
    )
    return selected


def resolve_query(query: str, search_kind: str | None = None) -> str:
    query = query.strip()
    parsed = urllib.parse.urlparse(query)

    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.lower().removeprefix("www.")
        if host not in YOUTUBE_HOSTS:
            raise ValueError("YouTube 링크나 검색어만 사용할 수 있어요.")
        return query

    if search_kind in {"album", "playlist"}:
        return build_youtube_playlist_search_url(query, search_kind)

    return build_youtube_search_query(query)
