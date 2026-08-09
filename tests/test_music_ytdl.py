import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import bot
import music_ytdl


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class YtdlProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        music_ytdl.ytdl_cache.clear()
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def asyncTearDown(self) -> None:
        music_ytdl.ytdl_cache.clear()
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    def test_default_options_leave_youtube_client_selection_to_ytdl(self) -> None:
        extractor_args = bot.YTDL_BASE_OPTIONS.get("extractor_args", {})
        youtube_args = extractor_args.get("youtube", {})

        self.assertNotIn("player_client", youtube_args)
        self.assertNotEqual(youtube_args.get("fetch_pot"), ["always"])

    async def test_repeated_query_uses_cache_without_a_second_worker(self) -> None:
        payload = {"id": "cachetest01", "title": "cached result"}
        worker = AsyncMock(return_value=payload)

        with (
            patch.object(music_ytdl, "run_ytdl_worker", new=worker),
            patch.object(music_ytdl, "YTDL_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(music_ytdl, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
                job_kind=music_ytdl.YtdlJobKind.USER_REQUEST,
            )
            first["title"] = "caller mutation"
            second = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
                job_kind=music_ytdl.YtdlJobKind.USER_REQUEST,
            )

        worker.assert_awaited_once()
        self.assertEqual(second["title"], "cached result")

    async def test_timed_out_worker_process_is_stopped(self) -> None:
        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                await asyncio.Event().wait()
                return b"", b""

        process = FakeProcess()
        stop_worker = AsyncMock()
        with (
            patch.object(
                music_ytdl.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch.object(music_ytdl, "stop_ytdl_worker", new=stop_worker),
            self.assertRaises(asyncio.TimeoutError),
        ):
            await music_ytdl.run_ytdl_worker({}, "timeout-test", 0.01)

        stop_worker.assert_awaited_once_with(process)

    async def test_repeated_cancellation_waits_for_process_cleanup(self) -> None:
        communicate_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()
        cleanup_cancelled = asyncio.Event()

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                await asyncio.Event().wait()
                return b"", b""

        async def stop_worker(process: object) -> None:
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise
            cleanup_finished.set()

        with (
            patch.object(
                music_ytdl.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(music_ytdl, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            worker = asyncio.create_task(
                music_ytdl.run_ytdl_worker({}, "repeated-cancel", 5.0)
            )
            await communicate_started.wait()
            worker.cancel()
            await cleanup_started.wait()
            worker.cancel()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(worker.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertTrue(cleanup_finished.is_set())

    async def test_worker_log_includes_queue_wait_and_execution_time(self) -> None:
        class FakeProcess:
            returncode = 0
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                response = json.dumps({"info": {"id": "logged"}}).encode("utf-8")
                return response, b""

        with (
            patch.object(
                music_ytdl.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            self.assertLogs("music-bot", level="INFO") as logs,
        ):
            result = await music_ytdl.run_ytdl_worker(
                {},
                "log-test",
                1.0,
                label="stream log test",
                job_kind=music_ytdl.YtdlJobKind.PLAYBACK_STREAM.log_name,
                priority=str(int(music_ytdl.YtdlJobKind.PLAYBACK_STREAM)),
                queue_wait_seconds=0.25,
            )

        output = "\n".join(logs.output)
        self.assertEqual(result["id"], "logged")
        self.assertIn("queue_wait=0.250s", output)
        self.assertIn("worker=", output)
        self.assertIn("response_bytes=", output)

    async def test_worker_entrypoint_returns_a_structured_error(self) -> None:
        with self.assertRaises(RuntimeError):
            await music_ytdl.run_ytdl_worker({}, "", 5.0)

    async def test_extraction_slot_is_released_after_worker_timeout(self) -> None:
        scheduler = music_ytdl.YtdlPriorityScheduler(1)
        worker = AsyncMock(
            side_effect=[asyncio.TimeoutError, {"id": "next-request"}],
        )
        with (
            patch.object(bot, "ytdl_scheduler", scheduler),
            patch.object(music_ytdl, "YTDL_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(music_ytdl, "run_ytdl_worker", new=worker),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await bot.extract_ytdl_info(
                    bot.YTDL_OPTIONS,
                    "ytsearch1:worker-timeout-test",
                    "worker timeout test",
                    job_kind=music_ytdl.YtdlJobKind.USER_REQUEST,
                    use_cache=False,
                )

            result = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:worker-after-timeout",
                "worker after timeout",
                job_kind=music_ytdl.YtdlJobKind.USER_REQUEST,
                use_cache=False,
            )

        await scheduler.shutdown()
        self.assertEqual(result["id"], "next-request")
        self.assertEqual(worker.await_count, 2)

    async def test_rate_limiter_waits_before_the_next_worker(self) -> None:
        music_ytdl.ytdl_last_request_started_at = music_ytdl.time.monotonic()
        with (
            patch.object(music_ytdl, "YTDL_MIN_INTERVAL_SECONDS", 6.0),
            patch.object(music_ytdl.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            await music_ytdl.wait_for_ytdl_interval()

        sleep.assert_awaited_once()
        self.assertGreater(sleep.await_args.args[0], 5.0)
        self.assertLessEqual(sleep.await_args.args[0], 6.0)

    async def test_request_can_skip_the_general_interval(self) -> None:
        music_ytdl.ytdl_last_request_started_at = music_ytdl.time.monotonic()
        with patch.object(music_ytdl.asyncio, "sleep", new=AsyncMock()) as sleep:
            await music_ytdl.wait_for_ytdl_interval(0.0)

        sleep.assert_not_awaited()

    async def test_429_opens_circuit_and_blocks_new_worker(self) -> None:
        with patch.object(music_ytdl, "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800):
            opened = music_ytdl.trip_youtube_circuit(
                RuntimeError("HTTP Error 429: Too Many Requests")
            )

        self.assertTrue(opened)
        self.assertGreater(music_ytdl.get_youtube_circuit_retry_after(), 1700)

        worker = AsyncMock(return_value={"id": "should-not-run"})
        with (
            patch.object(music_ytdl, "run_ytdl_worker", new=worker),
            self.assertRaises(music_ytdl.YouTubeCircuitOpenError),
        ):
            await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:circuit-open-test",
                "circuit test",
                job_kind=music_ytdl.YtdlJobKind.USER_REQUEST,
                use_cache=False,
            )

        worker.assert_not_awaited()

    def test_only_rate_limit_errors_trip_the_circuit(self) -> None:
        self.assertTrue(
            music_ytdl.is_youtube_block_error(RuntimeError("Sign in to confirm you're not a bot"))
        )
        self.assertFalse(music_ytdl.is_youtube_block_error(RuntimeError("Video unavailable")))


class YtdlPrioritySchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None
        self.scheduler = music_ytdl.YtdlPriorityScheduler(1)

    async def asyncTearDown(self) -> None:
        await self.scheduler.shutdown()
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def submit(
        self,
        query: str,
        job_kind: music_ytdl.YtdlJobKind,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict:
        return await self.scheduler.submit(
            {},
            query,
            query,
            job_kind=job_kind,
            timeout_seconds=timeout_seconds,
            minimum_interval_seconds=0.0,
        )

    async def assert_priority_order(
        self,
        lower_kind: music_ytdl.YtdlJobKind,
        higher_kind: music_ytdl.YtdlJobKind,
    ) -> list[str]:
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            order.append(query)
            if query == "blocker":
                started.set()
                await release.wait()
            return {"id": query}

        with patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("blocker", music_ytdl.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()

            lower = asyncio.create_task(self.submit("lower", lower_kind))
            await asyncio.sleep(0)
            higher = asyncio.create_task(self.submit("higher", higher_kind))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(blocker, lower, higher)

        return order

    async def test_playback_stream_runs_before_queued_autoplay(self) -> None:
        order = await self.assert_priority_order(
            music_ytdl.YtdlJobKind.AUTOPLAY,
            music_ytdl.YtdlJobKind.PLAYBACK_STREAM,
        )

        self.assertEqual(order, ["blocker", "higher", "lower"])

    async def test_submit_replaces_done_worker_before_callback_cleanup(self) -> None:
        finished_worker = asyncio.create_task(asyncio.sleep(0))
        await finished_worker
        self.scheduler.worker_tasks.add(finished_worker)

        with patch.object(
            music_ytdl,
            "run_ytdl_worker",
            new=AsyncMock(return_value={"id": "replacement"}),
        ):
            result = await self.submit(
                "replacement",
                music_ytdl.YtdlJobKind.USER_REQUEST,
            )

        self.assertEqual(result["id"], "replacement")
        self.assertNotIn(finished_worker, self.scheduler.worker_tasks)

    async def test_playback_preempts_autoplay_rate_limit_wait(self) -> None:
        autoplay_waiting = asyncio.Event()
        autoplay_release = asyncio.Event()
        executed: list[str] = []

        async def interval_wait(
            minimum_interval: float | None = None,
            *,
            on_interval_reserved: object = None,
        ) -> None:
            if minimum_interval is None:
                autoplay_waiting.set()
                await autoplay_release.wait()
            if callable(on_interval_reserved):
                on_interval_reserved()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            executed.append(query)
            return {"id": query}

        with (
            patch.object(music_ytdl, "wait_for_ytdl_interval", side_effect=interval_wait),
            patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker),
        ):
            autoplay = asyncio.create_task(
                self.scheduler.submit(
                    {},
                    "autoplay",
                    "autoplay",
                    job_kind=music_ytdl.YtdlJobKind.AUTOPLAY,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=None,
                )
            )
            await autoplay_waiting.wait()
            playback = await asyncio.wait_for(
                self.scheduler.submit(
                    {},
                    "playback",
                    "playback",
                    job_kind=music_ytdl.YtdlJobKind.PLAYBACK_STREAM,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=0.0,
                ),
                timeout=0.2,
            )
            autoplay.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await autoplay
            autoplay_release.set()

        self.assertEqual(playback["id"], "playback")
        self.assertEqual(executed, ["playback"])

    async def test_reserved_rate_slot_is_not_cancelled_before_worker_start(self) -> None:
        slot_reserved = asyncio.Event()
        release_interval = asyncio.Event()
        order: list[str] = []
        interval_calls = 0

        async def interval_wait(
            minimum_interval: float | None = None,
            *,
            on_interval_reserved: object = None,
        ) -> None:
            nonlocal interval_calls
            interval_calls += 1
            if callable(on_interval_reserved):
                on_interval_reserved()
            if interval_calls == 1:
                slot_reserved.set()
                await release_interval.wait()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            order.append(query)
            return {"id": query}

        with (
            patch.object(music_ytdl, "wait_for_ytdl_interval", side_effect=interval_wait),
            patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker),
        ):
            autoplay = asyncio.create_task(
                self.scheduler.submit(
                    {},
                    "autoplay",
                    "autoplay",
                    job_kind=music_ytdl.YtdlJobKind.AUTOPLAY,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=None,
                )
            )
            await slot_reserved.wait()
            user = asyncio.create_task(
                self.submit("user", music_ytdl.YtdlJobKind.USER_REQUEST)
            )
            await asyncio.sleep(0)

            self.assertFalse(autoplay.done())
            self.assertFalse(user.done())
            release_interval.set()
            await asyncio.gather(autoplay, user)

        self.assertEqual(order, ["autoplay", "user"])

    async def test_user_search_runs_before_queued_autoplay(self) -> None:
        order = await self.assert_priority_order(
            music_ytdl.YtdlJobKind.AUTOPLAY,
            music_ytdl.YtdlJobKind.USER_REQUEST,
        )

        self.assertEqual(order, ["blocker", "higher", "lower"])

    async def test_cancelled_queued_autoplay_is_not_executed(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        executed: list[str] = []

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            executed.append(query)
            if query == "blocker":
                started.set()
                await release.wait()
            return {"id": query}

        with patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("blocker", music_ytdl.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            autoplay = asyncio.create_task(
                self.submit("cancelled-autoplay", music_ytdl.YtdlJobKind.AUTOPLAY)
            )
            await asyncio.sleep(0)
            autoplay.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await autoplay
            release.set()
            await blocker
            await self.scheduler.queue.join()

        self.assertEqual(executed, ["blocker"])

    async def test_worker_concurrency_never_exceeds_one(self) -> None:
        active = 0
        maximum_active = 0

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"id": query}

        with patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker):
            await asyncio.gather(
                *(
                    self.submit(f"job-{index}", music_ytdl.YtdlJobKind.USER_REQUEST)
                    for index in range(6)
                )
            )

        self.assertEqual(maximum_active, 1)

    async def test_subtitle_request_does_not_block_stream_resolution(self) -> None:
        subtitle_started = asyncio.Event()
        release_subtitle = asyncio.Event()
        track = make_track("subtitle")

        async def lyrics_job(*args: object) -> str:
            subtitle_started.set()
            await release_subtitle.wait()
            return "lyrics"

        worker = AsyncMock(return_value={"id": "stream"})
        with (
            patch.object(bot, "auxiliary_network_semaphore", asyncio.Semaphore(1)),
            patch.object(
                bot,
                "wait_for_youtube_subtitle_interval",
                new=AsyncMock(),
            ),
            patch.object(bot, "run_lyrics_job", side_effect=lyrics_job),
            patch.object(music_ytdl, "run_ytdl_worker", new=worker),
        ):
            subtitle = asyncio.create_task(
                bot.get_selected_youtube_subtitle(
                    track,
                    ("ko", "vtt", "https://example.test/subtitle"),
                    purpose="test",
                )
            )
            await subtitle_started.wait()
            stream = await asyncio.wait_for(
                self.submit("stream", music_ytdl.YtdlJobKind.PLAYBACK_STREAM),
                timeout=0.2,
            )
            release_subtitle.set()
            lyrics = await subtitle

        self.assertEqual(stream["id"], "stream")
        self.assertEqual(lyrics, "lyrics")
        worker.assert_awaited_once()

    async def test_subtitle_rechecks_circuit_after_rate_limit_wait(self) -> None:
        semaphore = asyncio.Semaphore(1)
        lyrics_job = AsyncMock(return_value="lyrics")

        async def open_circuit_during_wait() -> None:
            music_ytdl.youtube_circuit_open_until = music_ytdl.time.monotonic() + 60
            music_ytdl.youtube_circuit_reason = "test circuit"

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(
                bot,
                "wait_for_youtube_subtitle_interval",
                side_effect=open_circuit_during_wait,
            ),
            patch.object(bot, "run_lyrics_job", new=lyrics_job),
            self.assertRaises(music_ytdl.YouTubeCircuitOpenError),
        ):
            await bot.get_selected_youtube_subtitle(
                make_track("subtitle"),
                ("ko", "vtt", "https://example.test/subtitle"),
                purpose="test",
            )

        lyrics_job.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)

    async def test_multiple_guild_jobs_share_priority_and_single_worker(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []
        active = 0
        maximum_active = 0

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            order.append(query)
            if query == "guild-a-blocker":
                started.set()
                await release.wait()
            await asyncio.sleep(0)
            active -= 1
            return {"id": query}

        with patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("guild-a-blocker", music_ytdl.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            jobs = [
                asyncio.create_task(
                    self.submit("guild-a-autoplay", music_ytdl.YtdlJobKind.AUTOPLAY)
                ),
                asyncio.create_task(
                    self.submit("guild-b-autoplay", music_ytdl.YtdlJobKind.AUTOPLAY)
                ),
                asyncio.create_task(
                    self.submit("guild-a-user", music_ytdl.YtdlJobKind.USER_REQUEST)
                ),
                asyncio.create_task(
                    self.submit(
                        "guild-b-playback",
                        music_ytdl.YtdlJobKind.PLAYBACK_STREAM,
                    )
                ),
            ]
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(blocker, *jobs)

        self.assertEqual(
            order,
            [
                "guild-a-blocker",
                "guild-b-playback",
                "guild-a-user",
                "guild-a-autoplay",
                "guild-b-autoplay",
            ],
        )
        self.assertEqual(maximum_active, 1)

    async def test_scheduler_shutdown_does_not_recancel_worker_cleanup(self) -> None:
        communicate_started = asyncio.Event()
        communication_cancelled = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()
        cleanup_cancelled = asyncio.Event()
        stop_calls = 0

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    communication_cancelled.set()
                    raise
                return b"", b""

        async def stop_worker(process: object) -> None:
            nonlocal stop_calls
            stop_calls += 1
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise
            cleanup_finished.set()

        with (
            patch.object(
                music_ytdl.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(music_ytdl, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            submission = asyncio.create_task(
                self.submit(
                    "shutdown-cleanup",
                    music_ytdl.YtdlJobKind.USER_REQUEST,
                    timeout_seconds=5.0,
                )
            )
            await communicate_started.wait()
            shutdown = asyncio.create_task(self.scheduler.shutdown())
            await cleanup_started.wait()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(shutdown.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            await shutdown
            result = await asyncio.gather(submission, return_exceptions=True)

        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertEqual(stop_calls, 1)
        self.assertTrue(cleanup_finished.is_set())
        self.assertTrue(communication_cancelled.is_set())
        self.assertFalse(self.scheduler.active_jobs)
        self.assertFalse(self.scheduler.worker_tasks)

    async def test_caller_cancellation_overlapping_shutdown_cleans_once(self) -> None:
        communicate_started = asyncio.Event()
        communication_cancelled = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_cancelled = asyncio.Event()
        stop_calls = 0

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    communication_cancelled.set()
                    raise
                return b"", b""

        async def stop_worker(process: object) -> None:
            nonlocal stop_calls
            stop_calls += 1
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise

        with (
            patch.object(
                music_ytdl.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(music_ytdl, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            submission = asyncio.create_task(
                self.submit(
                    "caller-cancel-cleanup",
                    music_ytdl.YtdlJobKind.USER_REQUEST,
                    timeout_seconds=5.0,
                )
            )
            await communicate_started.wait()
            submission.cancel()
            await cleanup_started.wait()
            execution_task = next(iter(self.scheduler.active_jobs.values())).execution_task
            self.assertIsNotNone(execution_task)
            cancelling_count = execution_task.cancelling()

            shutdown = asyncio.create_task(self.scheduler.shutdown())
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertEqual(execution_task.cancelling(), cancelling_count)
            self.assertFalse(shutdown.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            await shutdown
            result = await asyncio.gather(submission, return_exceptions=True)

        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertEqual(stop_calls, 1)
        self.assertTrue(communication_cancelled.is_set())
        self.assertFalse(self.scheduler.active_jobs)
        self.assertFalse(self.scheduler.worker_tasks)

    async def test_shutdown_cancels_running_and_pending_jobs(self) -> None:
        started = asyncio.Event()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            started.set()
            await asyncio.Event().wait()
            return {"id": query}

        with patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker):
            running = asyncio.create_task(
                self.submit("running", music_ytdl.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            pending = asyncio.create_task(
                self.submit("pending", music_ytdl.YtdlJobKind.AUTOPLAY)
            )
            await asyncio.sleep(0)
            await self.scheduler.shutdown()
            results = await asyncio.gather(
                running,
                pending,
                return_exceptions=True,
            )

        self.assertTrue(
            all(isinstance(result, asyncio.CancelledError) for result in results)
        )
