import asyncio
import unittest
from collections import deque
from unittest.mock import AsyncMock, patch

import bot


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://music.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class QueueTests(unittest.TestCase):
    def test_remove_by_id_uses_stable_track_identity(self) -> None:
        first = make_track("first")
        second = make_track("second")
        third = make_track("third")
        state = bot.GuildMusicState(queue=deque([third, first, second]))

        removed = bot.remove_queued_track_by_id(state, second.track_id)

        self.assertIs(removed, second)
        self.assertEqual(list(state.queue), [third, first])


class PlaybackSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            if state.advance_task and not state.advance_task.done():
                state.advance_task.cancel()
        bot.music_states.clear()

    async def test_only_one_advance_task_is_scheduled_per_guild(self) -> None:
        gate = asyncio.Event()

        async def fake_play_next(guild_id: int, announce: bool = True) -> None:
            await gate.wait()

        with patch.object(bot, "play_next", side_effect=fake_play_next):
            first_task, first_created = bot.schedule_play_next(123)
            second_task, second_created = bot.schedule_play_next(123)

            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertIs(first_task, second_task)

            gate.set()
            await first_task

    async def test_concurrent_start_requests_only_pop_one_track(self) -> None:
        class FakeVoice:
            def __init__(self) -> None:
                self.play_calls = 0
                self.playing = False

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.play_calls += 1
                self.playing = True

        guild_id = 456
        first = make_track("first")
        second = make_track("second")
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.queue.extend([first, second])

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "resolve_track_stream", new=AsyncMock()),
            patch.object(bot.discord, "FFmpegPCMAudio", return_value=object()),
            patch.object(bot.discord, "PCMVolumeTransformer", return_value=object()),
        ):
            first_task, first_created = bot.schedule_play_next(guild_id, announce=False)
            second_task, second_created = bot.schedule_play_next(guild_id, announce=False)
            await asyncio.gather(first_task, second_task)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(voice.play_calls, 1)
        self.assertIs(state.current, first)
        self.assertEqual(list(state.queue), [second])

    async def test_fresh_stream_url_is_reused(self) -> None:
        track = make_track("fresh")
        track.stream_url = "https://example.test/audio"
        track.stream_resolved_at = bot.time.monotonic()

        with patch.object(bot, "extract_ytdl_info", new=AsyncMock()) as extract:
            await bot.resolve_track_stream(track)

        extract.assert_not_awaited()

    async def test_stale_stream_url_is_refreshed(self) -> None:
        track = make_track("stale")
        track.stream_url = "https://example.test/old-audio"
        track.stream_resolved_at = bot.time.monotonic() - bot.STREAM_URL_MAX_AGE_SECONDS
        resolved = {
            "title": "refreshed",
            "webpage_url": track.webpage_url,
            "url": "https://example.test/new-audio",
            "formats": [{}],
        }

        with patch.object(
            bot,
            "extract_ytdl_info",
            new=AsyncMock(return_value=resolved),
        ) as extract:
            await bot.resolve_track_stream(track)

        extract.assert_awaited_once()
        self.assertEqual(track.stream_url, "https://example.test/new-audio")
        self.assertEqual(track.title, "refreshed")

    async def test_extraction_slot_wait_also_times_out(self) -> None:
        with (
            patch.object(bot, "ytdl_semaphore", asyncio.Semaphore(0)),
            patch.object(bot, "YTDL_EXTRACT_TIMEOUT_SECONDS", 0.01),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await bot.extract_ytdl_info({}, "test", "blocked extraction")


if __name__ == "__main__":
    unittest.main()
