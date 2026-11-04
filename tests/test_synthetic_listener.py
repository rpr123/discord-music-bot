import threading
import unittest

from devtools import synthetic_listener


class FakeSource:
    def __init__(self, frames: int, error: Exception | None = None) -> None:
        self.frames = frames
        self._current_error = error
        self.cleaned_up = False

    def read(self) -> bytes:
        if self.frames == 0:
            return b""
        self.frames -= 1
        return b"frame"

    def cleanup(self) -> None:
        self.cleaned_up = True


class FakeVoiceTests(unittest.TestCase):
    def play(self, source: FakeSource) -> list[Exception | None]:
        voice = synthetic_listener.FakeVoice()
        finished = threading.Event()
        errors: list[Exception | None] = []

        def after(error: Exception | None) -> None:
            errors.append(error)
            finished.set()

        voice.play(source, after=after)
        self.assertTrue(finished.wait(2))
        voice._thread.join(2)
        self.assertFalse(voice.is_playing())
        return errors

    def test_source_error_reaches_after_like_discord_player(self) -> None:
        error = RuntimeError("FFmpeg exited with code 1")
        source = FakeSource(frames=2, error=error)

        self.assertEqual(self.play(source), [error])
        self.assertTrue(source.cleaned_up)

    def test_finished_source_reports_no_error(self) -> None:
        source = FakeSource(frames=3)

        self.assertEqual(self.play(source), [None])
        self.assertEqual(source.frames, 0)


if __name__ == "__main__":
    unittest.main()
