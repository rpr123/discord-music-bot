from __future__ import annotations

import argparse
import itertools
import logging
import time
from pathlib import Path

import bot as music_bot


class LocalMusicMode:
    def __init__(self, audio_path: Path, *, bulk_tracks: int = 3) -> None:
        resolved_path = audio_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise ValueError(f"Local test audio file was not found: {resolved_path}")
        self.audio_path = resolved_path
        self.bulk_tracks = max(1, min(bulk_tracks, music_bot.MAX_BULK_TRACKS))
        self.track_counter = itertools.count(1)

    def make_track(
        self,
        query: str,
        requester: str,
        requester_id: int | None = None,
    ) -> music_bot.Track:
        source_path = str(self.audio_path)
        sequence = next(self.track_counter)
        return music_bot.Track(
            title=f"[TEST {sequence}] {query}",
            webpage_url="",
            requester=requester,
            source_url=source_path,
            requester_id=requester_id,
            stream_url=source_path,
            stream_resolved_at=time.monotonic(),
        )

    def make_tracks(
        self,
        query: str,
        requester: str,
        count: int,
        requester_id: int | None = None,
    ) -> list[music_bot.Track]:
        return [
            self.make_track(query, requester, requester_id)
            for _ in range(count)
        ]

    async def extract_track(
        self,
        query: str,
        requester: str,
        search_kind: str | None = None,
        requester_id: int | None = None,
    ) -> music_bot.Track:
        del search_kind
        return self.make_track(query, requester, requester_id)

    async def extract_tracks(
        self,
        query: str,
        requester: str,
        search_kind: str | None = None,
        requester_id: int | None = None,
    ) -> list[music_bot.Track]:
        del search_kind
        return self.make_tracks(
            query,
            requester,
            self.bulk_tracks,
            requester_id,
        )

    async def extract_auto_tracks(
        self,
        query: str,
        requester: str,
        count: int,
        requester_id: int | None = None,
    ) -> list[music_bot.Track]:
        return self.make_tracks(
            query,
            requester,
            music_bot.clamp_auto_count(count),
            requester_id,
        )

    def install(self) -> None:
        music_bot.extract_track = self.extract_track
        music_bot.extract_tracks = self.extract_tracks
        music_bot.extract_auto_tracks = self.extract_auto_tracks
        music_bot.FFMPEG_OPTIONS = {"options": "-vn"}
        music_bot.NAMUWIKI_LYRICS_ENABLED = False
        music_bot.YOUTUBE_LYRICS_FALLBACK = False
        music_bot.lookup_track_lyrics = lambda track: None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Discord music bot with a local audio test fixture.",
    )
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--bulk-tracks", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mode = LocalMusicMode(args.audio_file, bulk_tracks=args.bulk_tracks)
    mode.install()
    logging.getLogger("music-bot").warning(
        "Local music test mode is enabled with %s; YouTube will not be queried.",
        mode.audio_path,
    )
    music_bot.main()


if __name__ == "__main__":
    main()
