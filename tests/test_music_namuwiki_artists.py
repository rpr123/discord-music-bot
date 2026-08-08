import unittest

import bot
import music_namuwiki_matching as music_namuwiki_artists
from music_models import Track


MOVED_NAMES = (
    "extract_namuwiki_primary_artist_from_tables",
    "get_namuwiki_track_artists",
    "namuwiki_artist_matches_track",
)


def make_track(title: str = "Song") -> Track:
    return Track(
        title=title,
        webpage_url="https://example.com/watch?v=test",
        requester="tester",
        source_url="https://example.com/watch?v=test",
    )


class MusicNamuWikiArtistsTests(unittest.TestCase):
    def test_bot_reexports_moved_artist_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_artists, name),
                )

    def test_primary_artist_uses_first_value_after_a_known_label(self) -> None:
        tables = [[["발매일", "2026"], ["ＡＲＴＩＳＴ", "", "SUPER BEAVER\n공식"]]]
        self.assertEqual(
            music_namuwiki_artists.extract_namuwiki_primary_artist_from_tables(
                tables
            ),
            "SUPER BEAVER",
        )

    def test_track_artist_prefers_metadata_then_falls_back_to_title(self) -> None:
        track = make_track("Ignored Artist「Song」")
        track.artist = "Ａｒｔｉｓｔ - Topic"
        self.assertEqual(
            music_namuwiki_artists.get_namuwiki_track_artists(track),
            ["Artist"],
        )

        track.artist = None
        self.assertEqual(
            music_namuwiki_artists.get_namuwiki_track_artists(track),
            ["Ignored Artist"],
        )

    def test_track_artist_can_be_inferred_around_song_name(self) -> None:
        track = make_track("SUPER BEAVER - らしさ")
        track.song_name = "らしさ"
        self.assertEqual(
            music_namuwiki_artists.get_namuwiki_track_artists(track),
            ["SUPER BEAVER"],
        )

    def test_artist_match_preserves_exact_partial_and_unknown_rules(self) -> None:
        track = make_track()
        track.artist = "Official髭男dism"

        self.assertTrue(
            music_namuwiki_artists.namuwiki_artist_matches_track(
                track, "Official髭男dism"
            )
        )
        self.assertTrue(
            music_namuwiki_artists.namuwiki_artist_matches_track(
                track, "Official髭男dism Music"
            )
        )
        self.assertFalse(
            music_namuwiki_artists.namuwiki_artist_matches_track(
                track, "SUPER BEAVER"
            )
        )
        self.assertTrue(
            music_namuwiki_artists.namuwiki_artist_matches_track(track, None)
        )
