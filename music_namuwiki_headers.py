from __future__ import annotations

import re
from typing import Callable


def namuwiki_translation_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "한국어번역" in key:
        return 100
    if "한국어해석" in key:
        return 95
    if "한국어가사" in key:
        return 90
    if key in {"번역", "해석", "한국어"}:
        return 70
    return 0


def namuwiki_source_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "일본어원문" in key or "원어원문" in key:
        return 100
    if key == "원문":
        return 90
    if key in {"일본어", "일어", "원어"}:
        return 70
    return 0


def namuwiki_reading_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if any(
        marker in key
        for marker in ("일본어독음", "한글독음", "한국어독음")
    ):
        return 100
    if "독음" in key:
        return 90
    if key in {"발음", "요미가나", "읽는법"}:
        return 70
    return 0


def best_namuwiki_header_column(
    row: list[str],
    scorer: Callable[[str], int],
    excluded: set[int],
) -> int | None:
    candidates = [
        (scorer(header), column_index)
        for column_index, header in enumerate(row)
        if column_index not in excluded and scorer(header) > 0
    ]
    return max(candidates)[1] if candidates else None
