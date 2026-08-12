import ast
import unittest
from pathlib import Path

import bot
import music_track_metadata


MOVED_FUNCTION_NAMES = (
    "get_video_id",
    "normalize_track_key",
    "get_track_video_id",
    "get_track_identity_keys",
    "get_resolved_stream_url",
    "get_audio_codec",
    "get_thumbnail_url",
    "get_entry_url",
    "get_manual_subtitles",
    "make_track_from_info",
)


class MusicTrackMetadataTests(unittest.TestCase):
    def test_bot_reexports_moved_track_metadata_functions(self) -> None:
        for name in MOVED_FUNCTION_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_track_metadata, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_track_metadata.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertEqual(
            imported_modules,
            {
                "__future__",
                "copy",
                "music_models",
                "music_search_scoring",
                "re",
                "time",
                "urllib.parse",
            },
        )

    @staticmethod
    def make_identity_track(
        title: str,
        video_id: str,
        *,
        artist: str | None = None,
        song_name: str | None = None,
        uploader: str | None = None,
    ) -> bot.Track:
        url = f"https://www.youtube.com/watch?v={video_id}"
        return bot.Track(
            title=title,
            webpage_url=url,
            requester="tester",
            source_url=url,
            artist=artist,
            song_name=song_name,
            uploader=uploader,
        )

    def test_mv_and_audio_metadata_share_the_same_song_key(self) -> None:
        mv = self.make_identity_track(
            "back number - Blue Amber (Official Music Video)",
            "aaaaaaaaaaa",
            artist="back number",
            song_name="Blue Amber",
        )
        audio = self.make_identity_track(
            "Blue Amber (Official Audio)",
            "bbbbbbbbbbb",
            artist="back number",
            song_name="Blue Amber",
        )

        self.assertNotEqual(mv.webpage_url, audio.webpage_url)
        self.assertEqual(
            music_track_metadata.normalize_track_key(mv),
            music_track_metadata.normalize_track_key(audio),
        )

    def test_mv_and_audio_titles_match_without_music_metadata(self) -> None:
        mv = self.make_identity_track(
            "Artist - Same Song (Official MV)",
            "ccccccccccc",
        )
        audio = self.make_identity_track(
            "Artist - Same Song [Official Audio]",
            "ddddddddddd",
        )

        self.assertEqual(
            music_track_metadata.normalize_track_key(mv),
            music_track_metadata.normalize_track_key(audio),
        )

    def test_topic_audio_matches_a_promotional_mv_title(self) -> None:
        mv = self.make_identity_track(
            "back number - ブルーアンバー 【ドラマ主題歌】",
            "nnnnnnnnnnn",
        )
        topic_audio = self.make_identity_track(
            "ブルーアンバー",
            "ooooooooooo",
            uploader="back number - Topic",
        )

        self.assertEqual(
            music_track_metadata.normalize_track_key(mv),
            music_track_metadata.normalize_track_key(topic_audio),
        )

    def test_live_remix_and_cover_remain_distinct_versions(self) -> None:
        studio = self.make_identity_track(
            "Artist - Same Song (Official Audio)",
            "eeeeeeeeeee",
        )
        live = self.make_identity_track(
            "Artist - Same Song (Official Live Video)",
            "fffffffffff",
        )
        remix = self.make_identity_track(
            "Artist - Same Song (Remix)",
            "ggggggggggg",
        )
        cover = self.make_identity_track(
            "Artist - Same Song (Cover)",
            "hhhhhhhhhhh",
        )

        keys = {
            music_track_metadata.normalize_track_key(studio),
            music_track_metadata.normalize_track_key(live),
            music_track_metadata.normalize_track_key(remix),
            music_track_metadata.normalize_track_key(cover),
        }
        self.assertEqual(len(keys), 4)

    def test_same_title_by_different_artists_remains_distinct(self) -> None:
        first = self.make_identity_track(
            "Same Song (Official Audio)",
            "iiiiiiiiiii",
            artist="First Artist",
            song_name="Same Song",
        )
        second = self.make_identity_track(
            "Same Song (Official Audio)",
            "jjjjjjjjjjj",
            artist="Second Artist",
            song_name="Same Song",
        )

        self.assertNotEqual(
            music_track_metadata.normalize_track_key(first),
            music_track_metadata.normalize_track_key(second),
        )

    def test_make_track_from_info_preserves_extracted_metadata(self) -> None:
        subtitle = {
            "ext": "vtt",
            "url": "https://example.test/subtitle",
            "metadata": {"source": "manual"},
        }
        info = {
            "id": "abcdefghijk",
            "title": "Song title",
            "url": "https://stream.example.test/audio",
            "requested_formats": [{"acodec": "opus"}],
            "duration": 245,
            "thumbnail": "https://example.test/cover.jpg",
            "artist": "Artist",
            "track": "Song title",
            "uploader": "Artist - Topic",
            "subtitles": {"ja": [subtitle]},
            "automatic_captions": {"ko": [{"url": "ignored"}]},
            "language": "ja",
            "_music_bot_extracted_at": 123.5,
        }

        track = music_track_metadata.make_track_from_info(
            info,
            "requester",
            "fallback",
            requester_id=42,
        )
        subtitle["metadata"]["source"] = "changed"

        self.assertEqual(track.title, "Song title")
        self.assertEqual(
            track.webpage_url,
            "https://www.youtube.com/watch?v=abcdefghijk",
        )
        self.assertEqual(track.source_url, track.webpage_url)
        self.assertEqual(track.requester, "requester")
        self.assertEqual(track.requester_id, 42)
        self.assertEqual(track.duration, 245)
        self.assertEqual(track.stream_url, "https://stream.example.test/audio")
        self.assertEqual(track.thumbnail_url, "https://example.test/cover.jpg")
        self.assertEqual(track.artist, "Artist")
        self.assertEqual(track.song_name, "Song title")
        self.assertEqual(track.uploader, "Artist - Topic")
        self.assertEqual(track.audio_codec, "opus")
        self.assertEqual(track.subtitle_language, "ja")
        self.assertEqual(track.stream_resolved_at, 123.5)
        self.assertEqual(
            track.manual_subtitles["ja"][0]["metadata"]["source"],
            "manual",
        )
        self.assertNotIn("ko", track.manual_subtitles)

    def test_flat_entries_do_not_expose_an_unresolved_stream_url(self) -> None:
        info = {
            "_type": "url",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "formats": [{"acodec": "opus"}],
        }

        self.assertIsNone(music_track_metadata.get_resolved_stream_url(info))
        self.assertIsNone(
            music_track_metadata.get_resolved_stream_url(
                {"url": "https://stream.example.test/audio"}
            )
        )
