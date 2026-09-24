from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from music_config import (
    AUTOPLAY_LOG_BACKUP_COUNT,
    AUTOPLAY_LOG_ENABLED,
    AUTOPLAY_LOG_FILE,
    AUTOPLAY_LOG_MAX_BYTES,
    logger,
)


_handler: RotatingFileHandler | None = None
_write_failed = False


def log_autoplay_event(event: str, **details: object) -> None:
    """Keep bounded, independent JSONL diagnostics without breaking playback."""
    global _handler, _write_failed
    if not AUTOPLAY_LOG_ENABLED:
        return
    try:
        message = json.dumps(
            {
                "schema_version": 1,
                "policy_version": "fresh_first_v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **details,
            },
            ensure_ascii=False,
        )
        if _handler is None:
            AUTOPLAY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _handler = RotatingFileHandler(
                AUTOPLAY_LOG_FILE,
                maxBytes=AUTOPLAY_LOG_MAX_BYTES,
                backupCount=AUTOPLAY_LOG_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            _handler.setFormatter(logging.Formatter("%(message)s"))
        _handler.handle(logging.LogRecord(
            "autoplay-diagnostics", logging.INFO, __file__, 0, message, (), None,
        ))
    except (OSError, ValueError, TypeError):
        if not _write_failed:
            logger.warning("Could not write autoplay diagnostics", exc_info=True)
            _write_failed = True


def describe_autoplay_track(track) -> dict:
    # Only public music metadata; never requester IDs, cookies or stream URLs.
    return {
        "track_id": track.track_id,
        "search_id": getattr(track, "_autoplay_search_id", None),
        "title": track.title,
        "quality_score": getattr(track, "_autoplay_score", None),
        "source_index": getattr(track, "_autoplay_source_index", None),
    }
