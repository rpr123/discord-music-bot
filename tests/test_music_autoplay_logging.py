import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import bot
import music_autoplay_logging as diagnostics
from music_models import GuildMusicState, Track


def track(title, video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    return Track(title=title, webpage_url=url, source_url=url, requester="private-user")


class AutoplayLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "logs" / "autoplay.jsonl"
        for name, value in (
            ("AUTOPLAY_LOG_ENABLED", True),
            ("AUTOPLAY_LOG_FILE", self.path),
            ("AUTOPLAY_LOG_MAX_BYTES", 5 * 1024 * 1024),
            ("AUTOPLAY_LOG_BACKUP_COUNT", 2),
            ("_handler", None),
            ("_write_failed", False),
        ):
            patcher = patch.object(diagnostics, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.close_handler)

    def close_handler(self):
        if diagnostics._handler is not None:
            diagnostics._handler.close()

    def read_events(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_utf8_rotation_and_disabled_logging(self):
        with patch.object(diagnostics, "AUTOPLAY_LOG_MAX_BYTES", 500):
            for index in range(20):
                diagnostics.log_autoplay_event("test", title="한국어 노래", index=index)
        paths = list(self.path.parent.iterdir())
        self.assertEqual(len(paths), 3)
        self.assertEqual(self.read_events()[-1]["index"], 19)
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertEqual(json.loads(line)["title"], "한국어 노래")
        before = self.path.read_bytes()
        with patch.object(diagnostics, "AUTOPLAY_LOG_ENABLED", False):
            diagnostics.log_autoplay_event("disabled")
        self.assertEqual(self.path.read_bytes(), before)

    def test_unwritable_path_does_not_interrupt_playback_or_flood_warnings(self):
        self.path.parent.parent.joinpath("logs").write_text("not a directory")
        with patch.object(diagnostics.logger, "warning") as warning:
            diagnostics.log_autoplay_event("first")
            diagnostics.log_autoplay_event("second")
        warning.assert_called_once()
        self.assertIsNone(diagnostics._handler)

    async def test_search_selection_and_cache_are_correlated_in_real_jsonl(self):
        seed = track("시드", "sssssssssss")
        recent = track("최근 곡", "rrrrrrrrrrr")
        state = GuildMusicState(current=seed, autoplay_enabled=True)
        state.voice = MagicMock()
        state.voice.is_connected.return_value = True
        bot.remember_autoplay_track(state, recent)
        entries = [
            {"id": "sssssssssss", "title": "시드", "duration": 200},
            {"id": "rrrrrrrrrrr", "title": "최근 곡", "duration": 200},
            {"id": "aaaaaaaaaaa", "title": "새 곡 A", "duration": 200,
             "url": "https://secret.invalid/stream?token=private-secret"},
            {"id": "bbbbbbbbbbb", "title": "새 곡 B", "duration": 200},
            {"id": "aaaaaaaaaaa", "title": "중복 영상", "duration": 200},
            {"id": "bad", "title": "무효", "duration": 200,
             "webpage_url": "https://example.test/invalid"},
        ]
        with (
            patch.object(bot, "get_state", return_value=state),
            patch.object(bot, "extract_ytdl_info", new=AsyncMock(return_value={"entries": entries})),
            patch.object(bot, "update_control_panel", new=AsyncMock()),
        ):
            await bot.refill_autoplay_queue(999, state.playback_generation, seed)
        events = self.read_events()
        search = next(e for e in events if e["event"] == "search_results")
        selected = next(e for e in events if e["event"] == "selection" and e["source"] == "search")
        cached = next(e for e in events if e["event"] == "selection" and e["source"] == "cache")
        self.assertEqual(len(search["candidates"]), len(entries))
        self.assertIn("seed_or_duplicate", {c["status"] for c in search["candidates"]})
        self.assertIn("invalid_video_id", {c["status"] for c in search["candidates"]})
        queued = next(c for c in selected["candidates"] if c["status"] == "queued")
        self.assertEqual(queued["search_id"], search["search_id"])
        self.assertFalse(queued["is_recent"])
        recent_record = next(c for c in selected["candidates"] if c["is_recent"])
        self.assertGreater(recent_record["recent_penalty"], 0)
        self.assertGreaterEqual(recent_record["seconds_since_last_play"], 0)
        self.assertTrue(any(c["status"] == "hard_excluded" for c in selected["candidates"]))
        cached_queued = next(c for c in cached["candidates"] if c["status"] == "queued")
        self.assertEqual(cached_queued["search_id"], search["search_id"])
        self.assertEqual(len(state.queue), 2)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("private-user", text)
        self.assertNotIn("private-secret", text)
        self.assertNotIn("stream_url", text)

    async def test_search_logs_candidates_beyond_limit(self):
        seed = track("seed", "sssssssssss")
        entries = [
            {"id": "aaaaaaaaaaa", "title": "first", "duration": 200},
            {"id": "bbbbbbbbbbb", "title": "second", "duration": 200},
        ]
        with patch.object(bot, "extract_ytdl_info", new=AsyncMock(return_value={"entries": entries})):
            result = await bot.extract_auto_tracks_from_seed(
                seed, "tester", 2, job_kind=bot.YtdlJobKind.AUTOPLAY,
            )
        self.assertEqual(len(result), 2)
        self.assertEqual(
            [c["status"] for c in self.read_events()[0]["candidates"]],
            ["candidate", "candidate_limit"],
        )
