import asyncio
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import music_audio_diagnostics as diagnostics
import music_ytdl


IDLE_CPU = (100, 0, 50, 800, 0, 0, 0, 0)
# 400 ticks later: 100 busy, 100 idle, 200 stolen by the hypervisor.
STOLEN_CPU = (180, 0, 70, 900, 0, 0, 0, 200)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeSource:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.read_delay = 0.0
        self.cleaned_up = False

    def read(self) -> bytes:
        self.clock.now += self.read_delay
        return b"frame"

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        self.cleaned_up = True


class AudioLagLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "logs" / "audio-lag.jsonl"
        for name, value in (
            ("AUDIO_LAG_LOG_ENABLED", True),
            ("AUDIO_LAG_LOG_FILE", self.path),
            ("AUDIO_LAG_THRESHOLD_MS", 100),
            ("_handler", None),
            ("_write_failed", False),
        ):
            patcher = patch.object(diagnostics, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.close_handler)
        self.clock = FakeClock()
        self.source = FakeSource(self.clock)
        self.cpu_samples = [IDLE_CPU]

    def close_handler(self) -> None:
        if diagnostics._handler is not None:
            diagnostics._handler.close()

    def read_events(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]

    def make_monitored(self) -> diagnostics.LagMonitoredAudioSource:
        return diagnostics.LagMonitoredAudioSource(
            self.source,
            title="한국어 노래",
            get_ytdl_job_kinds=lambda: ("autoplay",),
            clock=self.clock,
            read_cpu=lambda: self.cpu_samples[-1],
        )

    def play_frames(
        self,
        monitored: diagnostics.LagMonitoredAudioSource,
        count: int,
    ) -> None:
        for _ in range(count):
            monitored.read()
            self.clock.now += diagnostics.AUDIO_FRAME_SECONDS

    def test_on_time_frames_are_not_logged(self) -> None:
        monitored = self.make_monitored()

        self.play_frames(monitored, 200)

        self.assertEqual(self.read_events(), [])

    def test_late_send_records_scheduling_cause_and_server_state(self) -> None:
        monitored = self.make_monitored()
        self.play_frames(monitored, 100)
        self.clock.now += 0.3
        self.cpu_samples.append(STOLEN_CPU)

        monitored.read()

        [event] = self.read_events()
        self.assertEqual(event["event"], "audio_lag")
        self.assertEqual(event["title"], "한국어 노래")
        self.assertEqual(event["late_ms"], 300)
        self.assertEqual(event["source_wait_ms"], 0)
        self.assertEqual(event["cause_hint"], "scheduling")
        self.assertEqual(event["position_seconds"], 2.0)
        self.assertEqual(event["ytdl_workers"], ["autoplay"])
        self.assertEqual(event["cpu"]["steal_percent"], 50.0)
        self.assertEqual(event["cpu"]["busy_percent"], 25.0)
        self.assertEqual(event["cpu"]["idle_percent"], 25.0)

    def test_stalled_stream_read_is_attributed_to_the_stream(self) -> None:
        monitored = self.make_monitored()
        self.play_frames(monitored, 10)
        self.source.read_delay = 0.5

        self.play_frames(monitored, 1)
        self.source.read_delay = 0.0
        monitored.read()

        [event] = self.read_events()
        self.assertEqual(event["source_wait_ms"], 500)
        self.assertEqual(event["cause_hint"], "stream")

    def test_bursts_within_a_second_are_counted_in_the_next_event(self) -> None:
        monitored = self.make_monitored()
        self.play_frames(monitored, 10)
        for _ in range(3):
            self.clock.now += 0.2
            self.play_frames(monitored, 1)
        self.clock.now += 1.0
        self.play_frames(monitored, 1)

        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["suppressed_since_last"], 0)
        self.assertEqual(events[1]["suppressed_since_last"], 2)

    def test_pause_gap_is_ignored_after_reset(self) -> None:
        monitored = self.make_monitored()
        self.play_frames(monitored, 10)
        self.clock.now += 30.0

        diagnostics.reset_audio_lag_timing(monitored)
        self.play_frames(monitored, 10)

        self.assertEqual(self.read_events(), [])

    def test_disabled_logging_and_missing_proc_files_do_not_break_reads(
        self,
    ) -> None:
        self.cpu_samples.append(None)
        monitored = self.make_monitored()
        self.play_frames(monitored, 2)
        self.clock.now += 0.5
        self.assertEqual(monitored.read(), b"frame")
        [event] = self.read_events()
        self.assertIsNone(event["cpu"])

        with patch.object(diagnostics, "AUDIO_LAG_LOG_ENABLED", False):
            self.clock.now += 5.0
            monitored.read()
        self.assertEqual(len(self.read_events()), 1)

    def test_wrapper_forwards_opus_flag_and_cleanup(self) -> None:
        monitored = self.make_monitored()

        self.assertTrue(monitored.is_opus())
        monitored.cleanup()

        self.assertTrue(self.source.cleaned_up)
        diagnostics.reset_audio_lag_timing(MagicMock())

    def test_proc_parsers_read_linux_formats(self) -> None:
        directory = Path(self.directory.name)
        stat = directory / "stat"
        stat.write_text(
            "cpu  10 1 5 80 2 0 1 3 0 0\ncpu0 1 2 3 4 5 6 7 8 0 0\n",
            encoding="ascii",
        )
        meminfo = directory / "meminfo"
        meminfo.write_text(
            "MemTotal: 1000000 kB\nMemAvailable:  204800 kB\n",
            encoding="ascii",
        )

        self.assertEqual(
            diagnostics.read_cpu_times(str(stat)),
            (10, 1, 5, 80, 2, 0, 1, 3),
        )
        self.assertEqual(diagnostics.read_mem_available_mb(str(meminfo)), 200)
        self.assertIsNone(diagnostics.read_cpu_times(str(directory / "none")))
        self.assertIsNone(diagnostics.describe_cpu_window(IDLE_CPU, IDLE_CPU, 1.0))

    def test_unwritable_path_warns_once(self) -> None:
        self.path.parent.parent.joinpath("logs").write_text("not a directory")
        with patch.object(diagnostics.logger, "warning") as warning:
            diagnostics.log_audio_lag_event("first")
            diagnostics.log_audio_lag_event("second")
        warning.assert_called_once()

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        tree = ast.parse(Path(diagnostics.__file__).read_text(encoding="utf-8"))
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
                "datetime",
                "discord",
                "json",
                "logging",
                "logging.handlers",
                "music_config",
                "os",
                "time",
                "typing",
            },
        )


class RunningWorkerTrackingTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_job_kind_is_visible_only_while_it_runs(self) -> None:
        seen_while_running: list[tuple[str, ...]] = []

        class FakeProcess:
            returncode = 0
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                seen_while_running.append(music_ytdl.get_running_ytdl_job_kinds())
                await asyncio.sleep(0)
                return json.dumps({"info": {"id": "tracked"}}).encode(), b""

        with patch.object(
            music_ytdl.asyncio,
            "create_subprocess_exec",
            new=AsyncMock(return_value=FakeProcess()),
        ):
            await music_ytdl.run_ytdl_worker(
                {}, "tracking-test", 1.0, job_kind="autoplay",
            )

        self.assertEqual(seen_while_running, [("autoplay",)])
        self.assertEqual(music_ytdl.get_running_ytdl_job_kinds(), ())


if __name__ == "__main__":
    unittest.main()
