# 아키텍처

이 문서는 현재 구현의 책임, 의존 방향, 상태 소유권과 런타임 흐름을 설명합니다. 현재 구조를 동결하거나 특정 리팩터링을 승인하는 정책 문서가 아닙니다. 코드, 테스트, CI와 이 문서가 충돌하면 실제 구현을 먼저 조사하고, 구조를 변경할 때 문서도 함께 갱신해야 합니다.

## 현재 의존 방향

`bot.py`는 Discord 진입점이자 composition root이며, 이벤트와 UI뿐 아니라 음성 재생, queue commit, 자동재생, 가사 게시와 shutdown을 잇는 런타임 구현도 포함합니다. 따라서 단순한 wiring 파일로 보거나, 반대로 파일 크기만으로 하나의 이동 경계를 정하면 안 됩니다.

Production supporting module들은 더 낮은 수준의 supporting module을 단방향으로 import할 수 있지만, 현재 production dependency graph에서는 `bot.py`를 역-import하지 않습니다. 주요 project-local import 방향은 다음과 같습니다.

- `bot` → 모든 `music_*` supporting module
- `music_ytdl` → `music_config`
- `music_discord_display` → `music_config`, `music_models`
- `music_search_scoring` → `music_config`, `music_discord_display`, `music_request_parsing`
- `music_track_metadata` → `music_models`, `music_search_scoring`
- `music_autoplay_policy` → `music_config`, `music_models`, `music_track_metadata`
- `music_lyrics_sources` → `music_config`, `music_models`, `music_search_scoring`
- `music_namuwiki` → config, lyrics source, models, parsing, search scoring, track metadata 계층
- `music_config`, `music_models`, `music_request_parsing`, `music_namuwiki_parsing`은 다른 project module을 import하지 않는 기반 계층
- `ytdl_worker`는 main bot module과 분리된 subprocess 진입점

`devtools/local_music_bot.py`는 개발 하네스를 설치하기 위해 의도적으로 `bot`을 import하고 런타임 함수를 교체합니다. Production import 규칙의 예외이며 배포 진입점이 아닙니다.

## Production module 책임

| 파일 | 현재 책임 |
| --- | --- |
| `bot.py` | Discord client와 event/command/view, 신청 추출과 queue commit, 음성 연결·재생·재시도, 자동재생 refill, panel·가사 lifecycle, process shutdown 조정 |
| `music_config.py` | `.env`와 설정값 파싱, yt-dlp·FFmpeg 옵션, logger, 길드별 channel/control message/autoplay 설정의 JSON 저장 |
| `music_models.py` | `Track`, `GuildMusicState`, autoplay/recent history entry와 queue·stream·retry에 가까운 mutation helper |
| `music_discord_display.py` | Discord 응답·삭제 helper와 track/player/queue/recent/lyrics embed 및 첨부 파일 생성 |
| `music_request_parsing.py` | YouTube URL·검색·playlist 구분과 album/playlist/auto 요청 파싱 |
| `music_search_scoring.py` | 제목·아티스트 정규화, YouTube Music result 변환, 일반 YouTube 후보 점수화와 query 해석 |
| `music_track_metadata.py` | yt-dlp info에서 video·stream·codec·thumbnail·subtitle metadata 추출, `Track` 생성과 identity key 구성 |
| `music_ytdl.py` | yt-dlp cache·rate limit·circuit breaker, priority job scheduling, timeout·cancellation과 subprocess 정리 |
| `ytdl_worker.py` | 격리 subprocess에서 `yt_dlp.YoutubeDL.extract_info`를 실행하고 JSON 결과 또는 오류 반환 |
| `music_autoplay_policy.py` | 최근곡 TTL/history, current·queue·recent 중복 제외, 후보 선택·pool 관리, seed·refill·retry 정책 |
| `music_lyrics_sources.py` | LRCLIB 조회·선택과 YouTube 수동 subtitle 후보 선택·다운로드·JSON3/VTT 파싱 |
| `music_namuwiki_parsing.py` | 나무마크·HTML table 파싱과 원문·독음·번역 행 추출 |
| `music_namuwiki.py` | 나무위키 문서 후보·아티스트 일치·override, API/HTML/preview 조회와 최종 가사 선택 |

## 상태 소유권

### Process-scoped runtime state

- `bot.py`는 Discord client, shutdown flag, YouTube Music client/cache/rate lock, 보조 network semaphore와 operation/worker task set, subtitle rate state, lyrics executor, voice operation과 housekeeping task를 소유합니다.
- `music_ytdl.py`는 process-wide priority scheduler, active worker/job, cache/rate state와 YouTube circuit state를 소유합니다.
- `music_namuwiki.py`는 동기 요청 lock, 마지막 요청 시각과 preview renderer 선택 상태를 소유합니다.

Process-scoped 상태가 모두 `bot.py`에 있다는 가정으로 소유권을 나누면 안 됩니다.

### Guild-scoped runtime state

`bot.music_states`가 guild ID별 `GuildMusicState`를 보관합니다. 각 state는 다음을 소유합니다.

- queue, current, voice, announcement channel과 repeat/skip/stop 상태
- persistent control message/view와 lyrics message/view, private lyrics message
- autoplay candidate pool, duplicate history와 실제 recent playback history
- 일반 state, voice connection, control panel을 위한 서로 다른 lock
- playback advance, delayed noncritical work, autoplay, lyrics, message cleanup, idle/empty disconnect task handle
- 오래된 callback과 await 결과를 무효화하는 playback generation과 task identity

### Track-scoped mutable state

`Track`은 입력 DTO만이 아닙니다. 기본 metadata와 requester 외에도 다음 mutable 상태를 보유합니다.

- stream URL, resolve 시각, audio codec
- playback attempt, transcode와 retry 상태
- 원문·한국어 가사 cache와 source
- manual subtitle metadata와 나무위키 조회 여부
- 곡별 한국어 가사 조회 lock

### Persisted configuration state

`music_config.py`는 길드별 music channel ID, control message ID와 autoplay enabled 값을 process map에 로드하고 `music_channels.json`에 저장합니다. Queue, current, history, stream cache와 task handle은 재시작 후 복구하는 persisted state가 아닙니다.

## 핵심 런타임 흐름

1. `on_message`가 설정된 music channel의 사용자 신청을 받고 음성 연결 조건을 확인한 뒤 `enqueue_tracks`를 호출합니다.
2. `enqueue_tracks`는 요청 종류를 파싱하고 YouTube Music metadata, 일반 YouTube fallback 또는 playlist/radio 추출을 선택합니다. 추출 결과는 `music_track_metadata`를 거쳐 `Track`이 됩니다.
3. 검색 전후 playback generation을 확인하고, 성공한 수동 신청은 진행 중인 autoplay refill과 숨은 후보를 정리한 뒤 `GuildMusicState.lock` 안에서 queue에 commit됩니다.
4. `schedule_play_next`와 pending advance 상태가 여러 completion callback을 하나의 다음 재생으로 합칩니다. `play_next`는 queue에서 current를 정하고 재생 직전에 stream을 resolve한 뒤 FFmpeg source를 voice client에 전달합니다.
5. 재생이 시작되면 실제 recent playback을 기록하고 panel을 갱신합니다. Voice completion callback은 repeat, retry, stop과 다음 advance를 결정합니다.
6. `start_noncritical_tasks`는 current identity와 generation을 다시 확인하면서 autoplay refill과 lyrics publish를 서로 다른 지연 뒤 시작합니다.
7. Autoplay는 pool 후보를 current·queue·recent 기준으로 다시 검증해 먼저 사용하고, 적격 후보가 없을 때만 radio extraction을 수행합니다.
8. Control panel은 같은 message를 복구·편집하며 message ID를 persisted configuration에 저장합니다. Lyrics는 track cache와 guild별 task/message/view 소유권을 사용해 곡 전환과 정지 때 취소·정리됩니다.

## Concurrency와 lifecycle

- 긴 network·executor 작업 전체를 guild state lock 안에서 수행하지 않습니다. Await 이후 queue/current를 변경하기 전에는 generation, current identity 또는 target 존재 여부를 다시 확인합니다.
- `GuildMusicState.lock`, `voice_connect_lock`, `control_panel_lock`은 각각 일반 재생 상태 commit, voice 연결·해제, persistent panel 조정을 담당합니다.
- Task finalizer는 자신이 여전히 state field의 owner일 때만 해당 참조를 비웁니다. 이전 task가 늦게 끝나 새 task의 소유권을 지우면 안 됩니다.
- Shutdown은 새 작업을 차단한 뒤 guild background task, voice operation, auxiliary operation, yt-dlp scheduler와 worker, lyrics executor, housekeeping task와 Discord client를 각 owner를 통해 정리합니다.

## 구조 변경을 검토할 때

- 행 수나 인접한 함수 범위가 아니라 하나의 책임과 mutable state owner를 먼저 정합니다.
- 동작만 옮기고 관련 mutable state를 원래 모듈에 남기는 이동은 피합니다.
- 새 owner가 `bot`을 역-import하거나 import-back, callback bundle, 순환 의존을 요구하는지 확인합니다.
- Patch는 symbol이 정의된 곳이 아니라 실행 코드가 실제 lookup하는 namespace에 적용합니다. Symbol 이동 전 `patch.object(bot, ...)`, re-export identity와 import contract test를 검색합니다.
- Pure policy·parsing·source behavior의 단위 테스트는 새 owner의 테스트로 이동하거나 추가할 수 있습니다. Discord wiring, cancellation, lock ordering과 guild lifecycle을 검증하는 integration test는 runtime owner에 남깁니다.
- 사용자에게 보이는 신청, queue, 재생, panel, lyrics, autoplay와 shutdown 동작이 유지되는지 실패·취소·경합 경로까지 검증합니다.

큰 연속 코드 영역이라는 사실만으로 하나의 추출 경계가 성립하지는 않습니다. 예를 들어 `run_lyrics_job`부터 `get_track_lyrics`, `get_track_korean_lyrics`, `LyricsVariantView`, `publish_current_lyrics`로 이어지는 영역은 process executor·auxiliary task, YouTube circuit, `Track` cache·lock과 Discord message/view lifecycle을 함께 사용합니다. 조회·cache 영역을 독립적으로 조사할 수는 있지만 새 owner가 이 상태를 어떻게 함께 소유할지도 제시해야 하며, 이는 추출 승인이나 반대를 의미하지 않습니다.

Voice 연결·이동·stale client 정리, `ensure_voice_channel` 계열, `stop_playback`, idle/empty disconnect와 playback scheduling도 개념적 묶음은 보입니다. 동시에 guild/voice lock, autoplay·lyrics cleanup, panel과 `play_next`에 연결되어 있으므로 실제 호출·상태·테스트 경계를 조사한 뒤 변경 범위를 정해야 합니다.
