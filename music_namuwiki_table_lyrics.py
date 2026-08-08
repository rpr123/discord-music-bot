from __future__ import annotations

from music_namuwiki_headers import (
    best_namuwiki_header_column,
    namuwiki_reading_header_score,
    namuwiki_source_header_score,
    namuwiki_translation_header_score,
)
from music_namuwiki_interleaved import (
    extract_interleaved_namuwiki_groups,
    extract_interleaved_namuwiki_lyrics,
    normalize_namuwiki_table_text,
)
from music_namuwiki_validation import (
    is_usable_namuwiki_lyrics,
    is_valid_korean_translation,
)
from music_script_detection import HANGUL_RE


def extract_namuwiki_lyrics_from_tables(
    tables: list[list[list[str]]],
) -> str | None:
    candidates: list[tuple[int, int, int, int, str]] = []
    for rows in tables:
        for header_row_index, row in enumerate(rows):
            for translation_index, header in enumerate(row):
                header_score = namuwiki_translation_header_score(header)
                if header_score == 0:
                    continue

                source_index = best_namuwiki_header_column(
                    row,
                    namuwiki_source_header_score,
                    {translation_index},
                )
                excluded = {translation_index}
                if source_index is not None:
                    excluded.add(source_index)
                reading_index = best_namuwiki_header_column(
                    row,
                    namuwiki_reading_header_score,
                    excluded,
                )

                groups: list[str] = []
                translated_cells: list[str] = []
                complete_group_count = 0
                for candidate_row in rows[header_row_index + 1 :]:
                    if any(
                        namuwiki_translation_header_score(cell) >= header_score
                        for cell in candidate_row
                    ):
                        break
                    if translation_index >= len(candidate_row):
                        continue
                    translation = normalize_namuwiki_table_text(
                        candidate_row[translation_index]
                    )
                    if (
                        not translation
                        or namuwiki_translation_header_score(translation)
                    ):
                        continue

                    group_lines: list[str] = []
                    source = ""
                    reading = ""
                    if (
                        source_index is not None
                        and source_index < len(candidate_row)
                    ):
                        source = normalize_namuwiki_table_text(
                            candidate_row[source_index]
                        )
                        if source:
                            group_lines.append(source)
                    if (
                        reading_index is not None
                        and reading_index < len(candidate_row)
                    ):
                        reading = normalize_namuwiki_table_text(
                            candidate_row[reading_index]
                        )
                        if reading:
                            group_lines.append(reading)
                    group_lines.append(translation)
                    groups.append("\n".join(group_lines))
                    translated_cells.append(translation)
                    if source and reading:
                        complete_group_count += 1

                translation = "\n".join(translated_cells).strip()
                if not translation or not is_valid_korean_translation(translation):
                    continue
                lyrics = "\n\n".join(groups)
                hangul_count = sum(
                    bool(HANGUL_RE.fullmatch(character))
                    for character in translation
                )
                candidates.append(
                    (
                        hangul_count,
                        complete_group_count,
                        header_score,
                        len(lyrics),
                        lyrics,
                    )
                )

        interleaved_lyrics = extract_interleaved_namuwiki_lyrics(rows)
        if interleaved_lyrics:
            groups, translated_lines, _ = extract_interleaved_namuwiki_groups(
                interleaved_lyrics
            )
            translation = "\n".join(translated_lines)
            hangul_count = sum(
                bool(HANGUL_RE.fullmatch(character))
                for character in translation
            )
            candidates.append(
                (
                    hangul_count,
                    len(groups),
                    50,
                    len(interleaved_lyrics),
                    interleaved_lyrics,
                )
            )

    if not candidates:
        return None
    lyrics = max(candidates, key=lambda candidate: candidate[:4])[4]
    return lyrics if is_usable_namuwiki_lyrics(lyrics) else None
