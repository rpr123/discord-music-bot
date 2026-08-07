from __future__ import annotations

import json
import sys

import yt_dlp


def main() -> int:
    try:
        request = json.load(sys.stdin)
        options = request.get("options")
        query = request.get("query")
        if not isinstance(options, dict) or not isinstance(query, str):
            raise ValueError("Invalid yt-dlp worker request.")

        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(query, download=False)
            sanitized = downloader.sanitize_info(info)
        response = {"info": sanitized}
        exit_code = 0
    except BaseException as error:
        response = {
            "error": str(error),
            "error_type": type(error).__name__,
        }
        exit_code = 1

    json.dump(response, sys.stdout, ensure_ascii=False)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
