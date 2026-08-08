from __future__ import annotations

from music_models import GuildMusicState, Track


AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)


def get_autoplay_seed(state: GuildMusicState) -> Track | None:
    if state.queue:
        return state.queue[-1]
    return state.current


def autoplay_can_refill(state: GuildMusicState, generation: int) -> bool:
    voice = state.voice
    return (
        state.autoplay_enabled
        and generation == state.playback_generation
        and voice is not None
        and voice.is_connected()
        and len(state.queue) <= 1
    )


def get_autoplay_retry_delay(failure_count: int) -> int:
    index = min(max(0, failure_count), len(AUTOPLAY_RETRY_DELAYS_SECONDS) - 1)
    return AUTOPLAY_RETRY_DELAYS_SECONDS[index]
