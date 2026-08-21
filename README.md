# Discord Music Bot

Python 기반 디스코드 음악 봇입니다. 음악 신청 전용 채널에서는 곡명이나 YouTube URL만 메시지로 보내도 바로 재생 대기열에 추가되고, 상시 컨트롤 패널에서 재생을 제어할 수 있습니다.

## 기능

- `/setupmusic` 음악 신청 전용 텍스트 채널 생성 또는 지정
- 전용 채널에 `아이유 좋은날`, `https://youtube.com/...`처럼 메시지만 보내서 재생
- 전용 채널에 `album: 앨범명`, `playlist: 플레이리스트명`처럼 보내서 통째로 추가
- 전용 채널에 `auto: 곡명`, `auto12: 곡명`, `auto 12: 곡명`처럼 보내서 관련 곡 여러 개 추가
- 컨트롤 패널에서 자동재생을 켜면 대기열이 1곡 이하일 때 관련 곡을 한 곡씩 계속 보충
- 곡명과 `auto` 시드는 YouTube Music 카탈로그를 먼저 확인하고 일반 YouTube를 fallback으로 사용
- YouTube 재생목록 링크를 보내면 여러 곡을 한 번에 대기열에 추가
- 전용 채널에 항상 유지되는 컨트롤 패널에서 재생 상태와 다음 곡을 확인하고 재생/일시정지, 스킵, 마지막 신청곡으로 이동, 정지, 반복, 셔플, 대기열 관리, 최근 재생곡 열람
- 현재 곡의 원문 가사를 별도 메시지로 자동 표시하고 곡이 바뀌면 같은 메시지를 갱신
- 음성 채널에서 사람이 모두 나가면 재생과 대기열을 정리하고 자동 퇴장
- 곡 검색과 추가는 전용 채널 메시지로만 처리

## 준비물

1. Python 3.11 이상
2. FFmpeg
3. Deno 2.3 이상
4. Discord Developer Portal에서 만든 봇 토큰

봇 권한은 서버 초대 URL을 만들 때 `applications.commands`, `bot`, `Connect`, `Speak`, `Use Voice Activity`, `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Manage Channels`, `Manage Messages`를 포함하세요.

초대 권한이 있어도 채널이나 카테고리 권한에서 봇 역할이 막혀 있으면 `Missing Permissions` 오류가 납니다. 음악 신청 채널과 명령어를 사용하는 채널에서 봇 역할에 `View Channel`, `Send Messages`, `Embed Links`, `Read Message History`, `Manage Messages`가 허용되어 있는지 확인하세요.

전용 채널에 보낸 곡명을 읽으려면 Discord Developer Portal의 봇 설정에서 `Message Content Intent`를 켜야 합니다.

## 설치

```powershell
cd C:\path\to\discord-music-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt`는 YouTube JavaScript 챌린지 스크립트를 포함하도록 `yt-dlp[default]`를 설치하고, YouTube Music 카탈로그 검색을 위해 `ytmusicapi`를 설치합니다. Deno도 설치한 뒤 `deno --version`으로 확인하세요. Ubuntu에서는 다음처럼 설치할 수 있습니다.

```bash
sudo apt update
sudo apt install -y ffmpeg unzip curl
curl -fsSL https://deno.land/install.sh | sh
export PATH="$HOME/.deno/bin:$PATH"
deno --version
```

FFmpeg가 PATH에 없다면 설치한 `ffmpeg.exe` 경로를 `.env`의 `FFMPEG_PATH`에 넣어 주세요.

Windows에서 FFmpeg를 설치하는 가장 간단한 방법:

```powershell
winget install Gyan.FFmpeg
```

설치 후 새 터미널을 열고 아래 명령으로 확인하세요.

```powershell
ffmpeg -version
```

위 명령이 안 되면 `.env`에 직접 경로를 넣어 주세요.

```env
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
```

## 설정

```powershell
Copy-Item .env.example .env
```

그리고 `.env`를 열어 `DISCORD_TOKEN`을 실제 봇 토큰으로 바꾸세요.

개발 중에는 `DEV_GUILD_ID`에 테스트 서버 ID를 넣으면 슬래시 명령어가 바로 갱신됩니다. 비워두면 전역 명령어로 등록되며, 디스코드 반영에 시간이 걸릴 수 있습니다.

곡명은 YouTube Music 카탈로그에서 먼저 찾습니다. 정식 `song`의 영상 ID가 제공되면 그 음원을 바로 재생하고, 예시처럼 비로그인 Music 검색에서 앨범만 보이면 앨범의 아티스트를 원래 검색어에 보강해 일반 YouTube에서 정식 음원을 찾습니다. Music 조회 실패나 빈 결과에는 기존 일반 YouTube 검색으로 자동 전환됩니다.

```env
MUSIC_CHANNEL_SILENT=true
MUSIC_CHANNEL_DELETE_REQUESTS=true
MUSIC_FEEDBACK_DELETE_SECONDS=10
EPHEMERAL_RESPONSE_DELETE_SECONDS=15
QUEUE_DELETE_RESPONSE_DELETE_SECONDS=30
LYRICS_API_URL=https://lrclib.net/api/search
LYRICS_REQUEST_TIMEOUT_SECONDS=10
NAMUWIKI_LYRICS_ENABLED=true
NAMUWIKI_PAGE_BASE_URL=https://namu.wiki/w
NAMUWIKI_API_BASE_URL=https://wiki-api.namu.la/api
# NAMUWIKI_API_TOKEN=
NAMUWIKI_PREVIEW_FALLBACK_ENABLED=true
NAMUWIKI_REQUEST_TIMEOUT_SECONDS=10
NAMUWIKI_REQUEST_INTERVAL_SECONDS=1.1
# NAMUWIKI_DOCUMENT_OVERRIDES={"video:abcdefghijk":"泥濘鳴鳴"}
# YOUTUBE_COOKIES_FILE=./cookies.txt
YTDL_EXTRACT_TIMEOUT_SECONDS=45
YTDL_MAX_CONCURRENT_EXTRACTIONS=1
YTDL_MIN_INTERVAL_SECONDS=6
YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS=6
YTDL_CACHE_TTL_SECONDS=180
YTDL_CACHE_MAX_ENTRIES=16
AUTOPLAY_START_DELAY_SECONDS=10
LYRICS_START_DELAY_SECONDS=3
IDLE_VOICE_DISCONNECT_DELAY_SECONDS=300
YOUTUBE_SEARCH_CANDIDATES=10
YOUTUBE_MUSIC_SEARCH_ENABLED=true
YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS=1
YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS=5
YOUTUBE_MUSIC_LANGUAGE=en
# YOUTUBE_MUSIC_LOCATION=KR
# YOUTUBE_MUSIC_AUTH_FILE=./ytmusic-auth.json
# YOUTUBE_MUSIC_OAUTH_CLIENT_ID=
# YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET=
YOUTUBE_CIRCUIT_BREAKER_SECONDS=1800
STREAM_URL_MAX_AGE_SECONDS=900
MAX_BULK_TRACKS=50
DEFAULT_AUTO_TRACKS=8
MAX_AUTO_TRACKS=25
AUTOPLAY_REFILL_CANDIDATES=10
AUTOPLAY_HISTORY_TTL_SECONDS=43200
```

`MUSIC_CHANNEL_SILENT=true`이면 음악 신청 전용 채널에서 봇이 보내는 검색/대기열/Now playing 메시지를 조용한 메시지로 보냅니다. 사용자가 직접 보낸 곡 신청 메시지의 알림이나 각자의 채널 음소거 상태는 디스코드 클라이언트 설정 영역이라 봇이 강제로 바꿀 수 없습니다.

`MUSIC_CHANNEL_DELETE_REQUESTS=true`이면 전용 채널에서 사용자가 보낸 곡 신청 메시지를 처리 후 삭제합니다. 검색 실패나 음성 채널 미입장처럼 재생을 시작하지 못한 경우에도 요청 메시지는 정리됩니다.

`MUSIC_FEEDBACK_DELETE_SECONDS=10`이면 메시지로 곡을 신청했을 때 나오는 임시 추가 확인 메시지를 10초 뒤 삭제합니다. 슬래시 명령어와 버튼의 일반 개인 응답은 신청자에게만 보이며 `EPHEMERAL_RESPONSE_DELETE_SECONDS=15`초 뒤 정리됩니다. 대기열 관리 메시지는 곡을 삭제할 때마다 만료 시간이 다시 계산되고, 마지막 삭제로부터 `QUEUE_DELETE_RESPONSE_DELETE_SECONDS=30`초 뒤 삭제됩니다.

마지막 곡이 끝나거나 정지 버튼으로 재생을 멈춘 뒤 대기열도 비어 있으면 `IDLE_VOICE_DISCONNECT_DELAY_SECONDS`가 지난 후 봇이 음성 채널에서 자동으로 나갑니다. 기본값은 `300`초(5분)이며, 그 전에 새 곡이 추가되거나 재생되면 기존 타이머를 취소합니다. 일시정지는 재생 중으로 취급해 타이머를 시작하지 않습니다. `0`으로 설정하면 사람이 남아 있는 동안의 유휴 자동 퇴장을 끌 수 있습니다. 사람이 모두 나간 빈 음성 채널에서 3초 뒤 나가는 기존 동작은 이 설정과 별개로 유지됩니다.

곡이 재생된 뒤 `LYRICS_START_DELAY_SECONDS`가 지나면 LRCLIB에서 현재 곡을 찾아 전용 채널에 별도의 원문 가사 메시지를 자동으로 보냅니다. LRCLIB에 결과가 없거나 조회에 실패하면 해당 YouTube 영상에서 제공하는 수동 자막을 한 번 더 확인하며, 자동 생성 자막은 가사로 사용하지 않습니다. 두 출처 모두 결과가 없으면 원문 메시지에는 `미제공`으로 표시합니다. 나무위키는 곡 전환 때 자동 조회하지 않고 `나무위키 가사` 버튼을 누를 때만 확인합니다. 자막 정보는 재생을 위해 이미 조회한 영상 정보에서 재사용하므로 별도의 영상 재검색은 하지 않습니다. 이후 곡이 바뀔 때는 원문 메시지를 수정하고, 재생목록이 완전히 끝나거나 정지·퇴장할 때 메시지를 삭제합니다. 같은 곡의 로마자판과 원문 문자판이 함께 검색되면 원문 문자판을 우선합니다. Discord 메시지 길이 제한을 넘는 가사는 같은 메시지의 UTF-8 텍스트 파일로 전체 원문을 첨부합니다. `LYRICS_REQUEST_TIMEOUT_SECONDS`는 각 가사 조회를 기다리는 최대 시간이며, `YOUTUBE_LYRICS_FALLBACK=false`로 수동 자막 fallback을 끌 수 있습니다.

원문이 한국어가 아니면 가사 메시지에 `나무위키 가사` 버튼이 표시됩니다. 외국어 곡의 원문을 LRCLIB와 YouTube에서 찾지 못해 `미제공`으로 표시된 경우에도 버튼은 남습니다. 버튼을 누른 사용자에게만 결과를 보여주며, 먼저 곡명과 같은 나무위키 문서의 가사 표에서 `원문 → 한글 독음 → 한국어 번역`의 세 줄 묶음을 순서 그대로 가져옵니다. 열로 나뉜 표와 한 셀 또는 여러 행에 세 줄씩 이어지는 표를 모두 처리하며, 접기 문구·제목 뜻·번역 없는 독음 행은 제외합니다. 성공한 결과에는 원문 문서 링크와 출처를 표시합니다. 나무위키 가사가 없고 업로더가 직접 제공한 YouTube 수동 한국어 자막만 사용할 수 있으면 버튼 이름이 `한국어 자막`으로 바뀝니다. 자동 생성 자막과 `tlang=ko` 기계 번역 자막은 사용하지 않습니다. 최초 성공 결과와 출처는 현재 곡에 캐시하며, 개인 가사 메시지는 해당 곡이 끝나거나 스킵·정지되면 바로 삭제됩니다.

`NAMUWIKI_LYRICS_ENABLED=true`는 나무위키 조회와 나무위키 가사 버튼을 켭니다. 기본값은 공개 문서 HTML을 `NAMUWIKI_REQUEST_INTERVAL_SECONDS` 이상의 간격으로 읽습니다. GCP에서 일반 페이지가 HTTP 403 또는 보안 확인 화면을 반환하면 `NAMUWIKI_PREVIEW_FALLBACK_ENABLED=true`가 같은 문서의 Discord 링크 미리보기용 HTML로 한 번 재시도하며, 성공한 프로세스에서는 이후 조회에도 그 경로를 우선 사용합니다. 별도 토큰은 필요하지 않습니다. `api_access` 권한이 있는 계정의 토큰을 `NAMUWIKI_API_TOKEN`에 넣은 경우에는 [the seed 공개 API](https://doc.theseed.io/)의 나무마크 원문을 가장 먼저 사용합니다. 영상 제목의 아티스트 접두사와 `Official MV` 같은 표시는 자동으로 제거합니다. 동명곡은 맨제목 문서의 `가수` 항목을 현재 트랙과 비교하며, 다르면 `곡명(아티스트)` 문서를 이어서 확인합니다. 그래도 문서명이 다르면 `NAMUWIKI_DOCUMENT_OVERRIDES`에 `video:YouTube영상ID` 또는 곡 식별 키와 정확한 문서명을 한 줄짜리 JSON 객체로 지정할 수 있습니다. 예를 들어 `{"video:keOnleW2eak":"らしさ(Official髭男dism)"}`처럼 설정합니다. 토큰은 `.env`에만 두고 커밋하지 마세요. 예전 기계번역용 `LYRICS_TRANSLATION_ENABLED` 설정은 더 이상 사용하지 않으므로 기존 `.env`에서 삭제해도 됩니다.

`YTDL_MIN_INTERVAL_SECONDS=6`은 일반 검색과 자동재생 보충 같은 yt-dlp 작업 사이에 최소 6초를 둡니다. yt-dlp 작업은 기본 한 개의 worker가 처리하며, 재생 직전 스트림 해석, 사용자 검색, 앨범·재생목록, 자동재생 순서로 대기 작업을 선택합니다. 현재 곡의 재생에 필요한 스트림 URL 해석은 이 간격을 기다리지 않으며, 아직 요청 간격을 기다리는 자동재생 작업보다 먼저 실행됩니다. 자동재생 보충은 재생 시작 후 `AUTOPLAY_START_DELAY_SECONDS`가 지난 뒤 실행됩니다. 가사는 `LYRICS_START_DELAY_SECONDS` 뒤에 시작해 FFmpeg·자동재생·가사 조회가 곡 전환 순간에 한꺼번에 몰리지 않게 합니다. 가벼운 YouTube Music 메타데이터와 YouTube 수동 자막 조회는 yt-dlp worker와 분리된 한 개의 보조 네트워크 슬롯을 사용합니다. Music 조회는 별도의 `YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS=1`을, 수동 자막은 `YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS=6`을 사용하므로 느린 자막 요청이 재생용 스트림 해석을 막지 않습니다. Music 결과와 일반 검색 결과는 `YTDL_CACHE_TTL_SECONDS` 동안 메모리에서 재사용하며, 기본 캐시 수는 저사양 서버에 맞춰 16개로 제한합니다. 일반 YouTube fallback은 `YOUTUBE_SEARCH_CANDIDATES`개의 가벼운 결과에서 제목 일치도, Music에서 얻은 아티스트, 길이, `Full Version`, `Short Ver.`, `Game MV` 같은 표시를 비교해 풀 버전을 우선합니다. 선택된 영상의 스트림은 실제 재생 직전에 준비하므로 오래 대기한 스트림 URL을 다시 받는 요청도 줄어듭니다. 직접 URL을 보냈거나 검색어에 `short`, `game mv`, `live`, `cover`, `off vocal` 같은 버전을 명시한 경우에는 Music 카탈로그를 건너뛰고 그 요청을 우선합니다. 후보 수는 최대 20입니다. 429 또는 봇 확인 오류가 감지되면 `YOUTUBE_CIRCUIT_BREAKER_SECONDS` 동안 새 YouTube 요청을 즉시 거절해 차단을 더 악화시키지 않습니다. 자동재생 검색 실패도 1분, 2분, 5분, 15분, 30분 순서로 간격을 늘려 재시도합니다.

YouTube Music의 비로그인 응답은 지역이나 시점에 따라 `songs` 목록을 비워 보낼 수 있습니다. 인증 없이도 앨범·아티스트 힌트와 일반 YouTube fallback은 동작하지만, 카탈로그 결과를 더 안정적으로 받으려면 [ytmusicapi OAuth 설정](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html)에 따라 별도 봇 계정으로 인증 파일을 만드세요.

```bash
ytmusicapi oauth --file ytmusic-auth.json \
  --client-id "클라이언트_ID" \
  --client-secret "클라이언트_시크릿"
```

생성된 파일을 `YOUTUBE_MUSIC_AUTH_FILE=./ytmusic-auth.json`으로 지정하고 같은 ID와 시크릿을 `YOUTUBE_MUSIC_OAUTH_CLIENT_ID`, `YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET`에 넣습니다. `ytmusic-auth.json`은 `.gitignore`에 포함되어 있으며 GitHub에 올리면 안 됩니다. Music 검색만 끄려면 `YOUTUBE_MUSIC_SEARCH_ENABLED=false`를 사용합니다.

GCP 같은 클라우드 서버에서 `Sign in to confirm you're not a bot` 오류가 나더라도 쿠키는 일반적인 요청 제한 해결책이 아닙니다. 계정 로그인이 꼭 필요한 콘텐츠에서만 별도 계정의 Netscape `cookies.txt`를 사용하고, GitHub에는 절대 올리지 마세요. Deno/EJS와 요청 제한을 구성해도 429가 계속되면 서버 출구 IP가 차단된 것이므로 다른 IP 또는 네트워크가 필요합니다.

`YTDL_EXTRACT_TIMEOUT_SECONDS`는 검색 한 번을 기다리는 최대 시간입니다. yt-dlp는 별도 작업 프로세스에서 실행되므로 타임아웃이나 취소가 발생하면 남은 작업도 함께 종료됩니다. `YTDL_MAX_CONCURRENT_EXTRACTIONS`는 동시에 실행할 검색 수를 제한해 느린 요청이 누적되는 것을 막습니다. 오래 대기한 곡은 `STREAM_URL_MAX_AGE_SECONDS`가 지나면 재생 직전에 스트림 주소를 새로 받습니다.

`MAX_BULK_TRACKS`는 앨범이나 재생목록을 한 번에 추가할 때 최대 몇 곡까지 대기열에 넣을지 정합니다.

`DEFAULT_AUTO_TRACKS`와 `MAX_AUTO_TRACKS`는 전용 채널의 `auto:` 요청으로 관련 곡을 추가할 때의 기본/최대 개수입니다. `AUTOPLAY_REFILL_CANDIDATES`는 재생 중 백그라운드 보충이 한 후보 목록에서 확인할 결과 수이며 기본값은 10입니다. 이는 검색 요청 횟수가 아니며, 라디오 목록에서 후보가 일부라도 나오면 별도의 보완 검색을 추가하지 않습니다. 한 번 조회한 목록에서 선별한 곡 중 최대 4곡은 길드별 메모리 후보 풀에 보관하고 다음 자동재생 보충에 먼저 재사용하므로, 후보가 유효한 동안 추가 라디오 조회를 건너뜁니다. 사용자가 직접 입력한 `auto25:` 같은 요청에는 이 후보 풀을 적용하지 않습니다. 자동재생 중복 방지는 최근 최대 50곡을 기억하며, 각 기록은 `AUTOPLAY_HISTORY_TTL_SECONDS`(기본 43200초, 12시간)가 지나거나 50곡 한도에서 먼저 밀려나면 다음 후보 검사 때 만료됩니다.

재생은 Opus 형식을 우선 선택하고 가능한 경우 재인코딩 없이 Discord로 전달합니다. 공용 `BOT_VOLUME` 처리는 CPU 절약을 위해 제거했으며, 음량은 각 사용자가 Discord에서 봇을 우클릭해 사용자 음량으로 조절합니다.

## YouTube 없는 서버 테스트

Discord 입장, 음성 재생, 컨트롤 패널, 대기열, 앨범, 자동재생을 시험할 때는 짧은 로컬 음원을 사용하면 YouTube 요청이 전혀 발생하지 않습니다.

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=15" test-tone.wav
```

일반 봇 대신 별도 개발용 진입점을 실행하세요.

```bash
python -m devtools.local_music_bot ./test-tone.wav --bulk-tracks 3
```

이 프로세스에서는 전용 채널에 어떤 곡명을 보내도 번호가 붙은 로컬 테스트 트랙이 생성됩니다. 일반 `python bot.py` 실행에는 테스트 코드나 테스트 설정이 적용되지 않습니다.

## 실행

```powershell
python bot.py
```

봇을 서버에 초대한 뒤 아래 순서로 사용하세요.

1. 관리 권한이 있는 사용자가 `/setupmusic`을 실행합니다.
2. 새로 만들어진 `#music` 채널 또는 지정한 채널에 들어갑니다.
3. 음성 채널에 들어간 상태로 전용 채널에 곡명이나 YouTube URL을 메시지로 보냅니다.

전용 채널 입력 예시:

```text
아이유 좋은날
album: NewJeans Get Up
playlist: lofi beats
auto: back number
auto12: lofi chill
auto 12: lofi chill
https://www.youtube.com/playlist?list=...
```

`/setupmusic`을 실행하면 전용 채널에 컨트롤 패널이 하나 만들어지고 봇을 재시작해도 같은 메시지를 다시 사용합니다. 저장된 메시지 ID가 유실된 경우에는 채널 기록에서 기존 패널을 복구합니다. 봇이 시작될 때는 가장 최신 패널 하나만 남기고 전용 채널의 다른 모든 메시지를 삭제합니다. 재생 중에는 다음 곡과 조작 버튼이 표시되고, 모든 곡이 끝나거나 정지하면 패널을 삭제하는 대신 재생 버튼이 비활성화된 “재생 대기 중” 상태로 돌아갑니다. 자동재생과 최근 재생 버튼은 대기 중에도 사용할 수 있습니다. `최근 재생` 버튼은 현재 실행 중 실제 재생을 시작한 고유 곡을 최신순으로 개인에게만 보여 줍니다. 자동재생 중복 방지와 같은 보관 기간(기본 12시간) 및 최대 50곡 제한을 사용하며, 같은 곡을 다시 재생하면 시각과 순서가 갱신됩니다. 건너뛰기만 한 자동재생 후보와 신청자 정보는 표시하지 않고, 메모리 기록이므로 봇을 재시작하면 초기화됩니다. 자동재생을 켜면 현재 흐름의 마지막 곡을 `auto:`와 같은 방식으로 검색하고, 현재 곡·대기열·최근 재생 곡과 겹치지 않는 후보 한 곡을 대기열이 1곡 이하일 때마다 추가합니다. 새 후보가 모두 최근 재생 이력에만 걸리면 추가 검색이나 이력 삭제 없이 같은 후보 목록에서 가장 오래전에 재생한 한 곡을 다시 사용합니다. 현재 곡·대기열·검색 기준곡은 이 예외를 적용하지 않습니다. 영상 ID가 달라도 아티스트와 곡명이 같은 MV, 공식 음원, 가사 영상은 같은 곡으로 보고, Live, Remix, Cover는 별도 버전으로 유지합니다. 안전하게 재사용할 후보가 없지만 다음 곡이 이미 대기 중이면 외부 검색 없이 재생 기준이 바뀔 때까지 기다렸다가 새 기준으로 다시 보충하고, 대기곡도 없거나 검색이 일시적으로 실패하면 자동재생을 끄거나 음성 채널에서 나갈 때까지 간격을 두고 다시 시도합니다.

`마지막 곡 재생` 버튼은 현재 곡과 가장 최근에 직접 신청한 곡 앞의 대기 곡을 한 번에 건너뜁니다. 처리 중 자동재생 곡이 뒤에 추가되더라도 클릭할 때 선택한 신청곡이 다음에 재생되며, 직접 신청한 대기 곡이 없으면 실제 마지막 대기 곡으로 이동합니다. 대기열 삭제 버튼을 누르면 곡 하나를 골라 삭제할 수 있습니다. 구간 삭제 버튼에서는 시작 곡과 끝 곡을 각각 선택해 양 끝을 포함한 구간 전체를 한 번에 삭제합니다. 대기열 관리 메시지는 마지막 삭제 30초 뒤, 메시지 신청의 곡 추가 확인은 10초 뒤 자동 삭제됩니다.

재생 중인 봇을 조작하거나 새 곡을 신청하려면 봇과 같은 음성 채널에 있어야 합니다. 봇이 재생 중일 때 다른 음성 채널의 요청으로 이동하지 않습니다.

전용 채널, 컨트롤 패널 메시지 ID, 자동재생 ON/OFF 설정은 `music_channels.json`에 서버별로 저장됩니다. 기존 채널 ID만 들어 있는 형식도 그대로 읽고, 다음 저장 때 새 형식으로 바뀝니다. 이 파일은 로컬 설정이라 Git에는 올리지 않도록 `.gitignore`에 넣어 두었습니다.

## 참고

- 음악 재생은 `yt-dlp`와 `FFmpeg`를 사용합니다.
- 곡명과 `auto` 시드는 동일한 YouTube Music 우선 검색을 사용합니다. 앨범·재생목록 텍스트는 기존 YouTube 재생목록 검색으로 처리합니다.
- 공개 영상은 쿠키 없이 먼저 시도하고, 계정이 필요한 콘텐츠에만 `YOUTUBE_COOKIES_FILE`을 사용하세요. 쿠키는 YouTube의 서버 IP 제한을 해제하지 않습니다.
- YouTube 쪽 변경으로 재생이 갑자기 실패하면 `python -m pip install --upgrade yt-dlp`로 업데이트해 보세요.
- 봇 토큰은 절대 GitHub나 채팅에 올리지 마세요.
