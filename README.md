# Discord Music Bot

Python 기반 디스코드 음악 봇입니다. 슬래시 명령어로 제어할 수 있고, 음악 신청 전용 채널에서는 곡명이나 YouTube URL만 메시지로 보내도 바로 재생 대기열에 추가됩니다.

## 기능

- `/setupmusic` 음악 신청 전용 텍스트 채널 생성 또는 지정
- 전용 채널에 `아이유 좋은날`, `https://youtube.com/...`처럼 메시지만 보내서 재생
- 전용 채널에 `album: 앨범명`, `playlist: 플레이리스트명`처럼 보내서 통째로 추가
- 전용 채널에 `auto: 곡명`, `auto12: 곡명`, `auto 12: 곡명`처럼 보내서 관련 곡 여러 개 추가
- 컨트롤 패널에서 자동재생을 켜면 대기열이 1곡 이하일 때 관련 곡을 한 곡씩 계속 보충
- 곡명과 `auto` 시드는 YouTube Music 카탈로그를 먼저 확인하고 일반 YouTube를 fallback으로 사용
- YouTube 재생목록 링크를 보내면 여러 곡을 한 번에 대기열에 추가
- 전용 채널에 항상 유지되는 컨트롤 패널에서 재생 상태와 다음 곡을 확인하고 재생/일시정지, 스킵, 정지, 반복, 셔플, 대기열 관리
- 현재 곡의 원문 가사를 별도 메시지로 자동 표시하고 곡이 바뀌면 같은 메시지를 갱신
- 음성 채널에서 사람이 모두 나가면 재생과 대기열을 정리하고 자동 퇴장
- `/join` 현재 음성 채널에 입장
- 곡 검색과 추가는 전용 채널 메시지로만 처리
- `/queue` 현재 재생 곡과 대기열 확인
- `/remove` 번호로 대기열 곡 삭제
- `/nowplaying` 현재 곡 확인
- `/pause` 일시정지
- `/resume` 다시 재생
- `/skip` 현재 곡 넘기기
- `/stop` 재생 중지 및 대기열 비우기
- `/leave` 음성 채널 퇴장

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

`requirements.txt`는 YouTube JavaScript 챌린지 스크립트를 포함하도록 `yt-dlp[default]`를 설치하고, YouTube Music 카탈로그 검색을 위해 `ytmusicapi`, 일본어 독음 생성을 위해 `SudachiPy`와 약 70MB 크기의 `SudachiDict-core` 사전을 설치합니다. Deno도 설치한 뒤 `deno --version`으로 확인하세요. Ubuntu에서는 다음처럼 설치할 수 있습니다.

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
LYRICS_TRANSLATION_ENABLED=true
LYRICS_READING_ENABLED=true
NAMUWIKI_LYRICS_ENABLED=true
NAMUWIKI_PAGE_BASE_URL=https://namu.wiki/w
NAMUWIKI_API_BASE_URL=https://wiki-api.namu.la/api
# NAMUWIKI_API_TOKEN=
NAMUWIKI_REQUEST_TIMEOUT_SECONDS=10
NAMUWIKI_REQUEST_INTERVAL_SECONDS=1.1
# NAMUWIKI_DOCUMENT_OVERRIDES={"video:abcdefghijk":"泥濘鳴鳴"}
# YOUTUBE_COOKIES_FILE=./cookies.txt
YTDL_EXTRACT_TIMEOUT_SECONDS=45
YTDL_MAX_CONCURRENT_EXTRACTIONS=1
YTDL_MIN_INTERVAL_SECONDS=6
YTDL_CACHE_TTL_SECONDS=600
YTDL_CACHE_MAX_ENTRIES=128
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
BOT_VOLUME=0.2
```

`MUSIC_CHANNEL_SILENT=true`이면 음악 신청 전용 채널에서 봇이 보내는 검색/대기열/Now playing 메시지를 조용한 메시지로 보냅니다. 사용자가 직접 보낸 곡 신청 메시지의 알림이나 각자의 채널 음소거 상태는 디스코드 클라이언트 설정 영역이라 봇이 강제로 바꿀 수 없습니다.

`MUSIC_CHANNEL_DELETE_REQUESTS=true`이면 전용 채널에서 사용자가 보낸 곡 신청 메시지를 처리 후 삭제합니다. 검색 실패나 음성 채널 미입장처럼 재생을 시작하지 못한 경우에도 요청 메시지는 정리됩니다.

`MUSIC_FEEDBACK_DELETE_SECONDS=10`이면 메시지로 곡을 신청했을 때 나오는 임시 추가 확인 메시지를 10초 뒤 삭제합니다. 슬래시 명령어와 버튼의 일반 개인 응답은 신청자에게만 보이며 `EPHEMERAL_RESPONSE_DELETE_SECONDS=15`초 뒤 정리됩니다. 대기열 관리 메시지는 곡을 삭제할 때마다 만료 시간이 다시 계산되고, 마지막 삭제로부터 `QUEUE_DELETE_RESPONSE_DELETE_SECONDS=30`초 뒤 삭제됩니다.

곡이 재생되기 시작하면 LRCLIB에서 현재 곡을 찾아 전용 채널에 별도의 원문 가사 메시지를 자동으로 보냅니다. LRCLIB에 결과가 없거나 조회에 실패하면 해당 YouTube 영상에서 제공하는 수동 자막을 한 번 더 확인하며, 자동 생성 자막은 가사로 사용하지 않습니다. 두 출처 모두 결과가 없으면 원문 메시지에는 `미제공`으로 표시합니다. 이때 나무위키에 원문·독음·번역 가사 표가 있으면 가사 본문을 공개하지 않고, 나무위키 가사가 있다는 짧은 안내와 원문 문서 링크를 두 번째 메시지로 표시합니다. 문서만 존재하거나 일반 설명·번역 표만 있고 실제 가사 구성이 없으면 안내하지 않습니다. 자막 정보는 재생을 위해 이미 조회한 영상 정보에서 재사용하므로 별도의 영상 재검색은 하지 않습니다. 이후 곡이 바뀔 때는 원문 메시지를 수정하고 이전 곡의 나무위키 안내를 정리하며, 재생목록이 완전히 끝나거나 정지·퇴장할 때 두 메시지를 모두 삭제합니다. 같은 곡의 로마자판과 원문 문자판이 함께 검색되면 원문 문자판을 우선합니다. Discord 메시지 길이 제한을 넘는 가사는 같은 메시지의 UTF-8 텍스트 파일로 전체 원문을 첨부합니다. `LYRICS_REQUEST_TIMEOUT_SECONDS`는 각 가사 조회를 기다리는 최대 시간이며, `YOUTUBE_LYRICS_FALLBACK=false`로 수동 자막 fallback을 끌 수 있습니다.

원문이 한국어가 아니면 가사 메시지에 `나무위키 가사` 버튼이 표시됩니다. 외국어 곡의 원문을 LRCLIB와 YouTube에서 찾지 못해 `미제공`으로 표시된 경우에도 버튼은 남습니다. 버튼을 누른 사용자에게만 결과를 보여주며, 먼저 곡명과 같은 나무위키 문서의 가사 표에서 `원문 → 한글 독음 → 한국어 번역`의 세 줄 묶음을 순서 그대로 가져옵니다. 열로 나뉜 표와 한 셀 또는 여러 행에 세 줄씩 이어지는 표를 모두 처리하며, 접기 문구·제목 뜻·번역 없는 독음 행은 제외합니다. 성공한 결과에는 원문 문서 링크와 출처를 표시합니다. 나무위키 가사가 없고 업로더가 직접 제공한 YouTube 수동 한국어 자막만 사용할 수 있으면 버튼 이름이 `한국어 자막`으로 바뀝니다. 자동 생성 자막과 `tlang=ko` 기계 번역 자막은 사용하지 않습니다. 최초 성공 결과와 출처는 현재 곡에 캐시하며, 개인 가사 메시지는 해당 곡이 끝나거나 스킵·정지되면 바로 삭제됩니다.

`NAMUWIKI_LYRICS_ENABLED=true`는 나무위키 조회를 켭니다. 기본값은 공개 문서 HTML을 `NAMUWIKI_REQUEST_INTERVAL_SECONDS` 이상의 간격으로 읽습니다. GCP처럼 공개 페이지 접근이 제한되는 환경에서는 `api_access` 권한이 있는 계정의 토큰을 `NAMUWIKI_API_TOKEN`에 넣으면 [the seed 공개 API](https://doc.theseed.io/)의 나무마크 원문을 먼저 사용합니다. 영상 제목의 아티스트 접두사와 `Official MV` 같은 표시는 자동으로 제거합니다. 그래도 문서명이 다르면 `NAMUWIKI_DOCUMENT_OVERRIDES`에 `video:YouTube영상ID` 또는 곡 식별 키와 정확한 문서명을 한 줄짜리 JSON 객체로 지정할 수 있습니다. 예를 들어 `{"video:abcdefghijk":"泥濘鳴鳴"}`처럼 설정합니다. 토큰은 `.env`에만 두고 커밋하지 마세요. `LYRICS_TRANSLATION_ENABLED=false`로 나무위키 가사 버튼 전체를, `NAMUWIKI_LYRICS_ENABLED=false`로 나무위키 조회만 끌 수 있습니다.

일본어 가사에는 `히라가나 독음` 버튼이 추가됩니다. 나무위키 3줄 가사에 일본어 독음이 있으면 그 값을 우선 사용하고, 독음이 한글 표기뿐이면 나무위키의 일본어 원문을 Sudachi로 변환합니다. LRCLIB 원문에도 같은 변환을 사용합니다. 원문에 `運命(さだめ)`, `運命（さだめ）`, `運命[さだめ]`, `運命【さだめ】`, `運命《さだめ》`, `｜超電磁砲《レールガン》`처럼 명시된 특수 독음이 있으면 사전 결과보다 우선합니다. 괄호 안이 일본어 가나이고 바로 앞에 한자가 있을 때만 독음으로 인식하므로 일반적인 괄호 속 코러스는 그대로 둡니다. `LYRICS_READING_ENABLED=false`로 독음 버튼을 끌 수 있습니다. 가사와 독음이 Discord 표시 한도를 넘으면 각각 UTF-8 텍스트 파일로 첨부합니다.

`YTDL_MIN_INTERVAL_SECONDS=6`은 검색 및 스트림 해석을 수행하는 yt-dlp 작업 사이에 최소 6초를 둡니다. 가벼운 YouTube Music 메타데이터 조회는 별도의 `YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS=1`을 사용하므로 일반 검색 시작을 불필요하게 6초 동안 막지 않습니다. Music 결과와 일반 검색 결과는 `YTDL_CACHE_TTL_SECONDS` 동안 메모리에서 재사용합니다. 일반 YouTube fallback은 `YOUTUBE_SEARCH_CANDIDATES`개의 가벼운 결과에서 제목 일치도, Music에서 얻은 아티스트, 길이, `Full Version`, `Short Ver.`, `Game MV` 같은 표시를 비교해 풀 버전을 우선합니다. 선택된 영상의 스트림은 대기열에 넣을 때 미리 해석하지 않고 실제 재생 직전에 준비하므로, 대기열 추가 결과가 먼저 표시되고 오래 대기한 스트림 URL을 다시 받는 요청도 줄어듭니다. 직접 URL을 보냈거나 검색어에 `short`, `game mv`, `live`, `cover`, `off vocal` 같은 버전을 명시한 경우에는 Music 카탈로그를 건너뛰고 그 요청을 우선합니다. 후보 수는 최대 20입니다. 429 또는 봇 확인 오류가 감지되면 `YOUTUBE_CIRCUIT_BREAKER_SECONDS` 동안 새 YouTube 요청을 즉시 거절해 차단을 더 악화시키지 않습니다. 자동재생 검색 실패도 1분, 2분, 5분, 15분, 30분 순서로 간격을 늘려 재시도합니다.

YouTube Music의 비로그인 응답은 지역이나 시점에 따라 `songs` 목록을 비워 보낼 수 있습니다. 인증 없이도 앨범·아티스트 힌트와 일반 YouTube fallback은 동작하지만, 카탈로그 결과를 더 안정적으로 받으려면 [ytmusicapi OAuth 설정](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html)에 따라 별도 봇 계정으로 인증 파일을 만드세요.

```bash
ytmusicapi oauth --file ytmusic-auth.json \
  --client-id "클라이언트_ID" \
  --client-secret "클라이언트_시크릿"
```

생성된 파일을 `YOUTUBE_MUSIC_AUTH_FILE=./ytmusic-auth.json`으로 지정하고 같은 ID와 시크릿을 `YOUTUBE_MUSIC_OAUTH_CLIENT_ID`, `YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET`에 넣습니다. `ytmusic-auth.json`은 `.gitignore`에 포함되어 있으며 GitHub에 올리면 안 됩니다. Music 검색만 끄려면 `YOUTUBE_MUSIC_SEARCH_ENABLED=false`를 사용합니다.

GCP 같은 클라우드 서버에서 `Sign in to confirm you're not a bot` 오류가 나더라도 쿠키는 일반적인 요청 제한 해결책이 아닙니다. 계정 로그인이 꼭 필요한 콘텐츠에서만 별도 계정의 Netscape `cookies.txt`를 사용하고, GitHub에는 절대 올리지 마세요. Deno/EJS와 요청 제한을 구성해도 429가 계속되면 서버 출구 IP가 차단된 것이므로 다른 IP 또는 네트워크가 필요합니다.

`YTDL_EXTRACT_TIMEOUT_SECONDS`는 검색 한 번을 기다리는 최대 시간입니다. `YTDL_MAX_CONCURRENT_EXTRACTIONS`는 동시에 실행할 검색 수를 제한해 느린 요청이 누적되는 것을 막습니다. 오래 대기한 곡은 `STREAM_URL_MAX_AGE_SECONDS`가 지나면 재생 직전에 스트림 주소를 새로 받습니다.

`MAX_BULK_TRACKS`는 앨범이나 재생목록을 한 번에 추가할 때 최대 몇 곡까지 대기열에 넣을지 정합니다.

`DEFAULT_AUTO_TRACKS`와 `MAX_AUTO_TRACKS`는 전용 채널의 `auto:` 요청으로 관련 곡을 추가할 때의 기본/최대 개수입니다.

`BOT_VOLUME`은 봇이 서버에 내보내는 기본 출력 음량입니다. `1.0`이 디스코드 사용자 음량 기준 `100` 정도라고 보면 되고, `0.2`는 `20` 정도의 낮은 시작값입니다. 디스코드 봇은 사용자별 음량을 강제로 설정할 수 없어서, 이후 개인별 조절은 각 사용자가 디스코드에서 봇을 우클릭해 사용자 음량을 바꾸면 됩니다.

## YouTube 없는 서버 테스트

Discord 입장, 음성 재생, 컨트롤 패널, 대기열, 앨범, 자동재생을 시험할 때는 짧은 로컬 음원을 사용하면 YouTube 요청이 전혀 발생하지 않습니다.

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=15" test-tone.wav
```

`.env`에 아래 값을 추가하고 봇을 재시작하세요.

```env
MUSIC_TEST_AUDIO_FILE=./test-tone.wav
MUSIC_TEST_BULK_TRACKS=3
```

이 상태에서는 전용 채널에 어떤 곡명을 보내도 번호가 붙은 로컬 테스트 트랙이 생성됩니다. 실제 YouTube 연동을 확인할 때는 `MUSIC_TEST_AUDIO_FILE` 줄을 제거하고 봇을 재시작한 뒤 한 곡만 시험하세요.

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

`/setupmusic`을 실행하면 전용 채널에 컨트롤 패널이 하나 만들어지고 봇을 재시작해도 같은 메시지를 다시 사용합니다. 저장된 메시지 ID가 유실된 경우에는 채널 기록에서 기존 패널을 복구합니다. 봇이 시작될 때는 가장 최신 패널 하나만 남기고 전용 채널의 다른 모든 메시지를 삭제합니다. 재생 중에는 다음 곡과 조작 버튼이 표시되고, 모든 곡이 끝나거나 정지하면 패널을 삭제하는 대신 재생 버튼이 비활성화된 “재생 대기 중” 상태로 돌아갑니다. 자동재생 버튼은 대기 중에도 켜고 끌 수 있습니다. 자동재생을 켜면 현재 흐름의 마지막 곡을 `auto:`와 같은 방식으로 검색하고, 현재 곡·대기열·최근 재생 곡과 겹치지 않는 후보 한 곡을 대기열이 1곡 이하일 때마다 추가합니다. 영상 ID가 달라도 아티스트와 곡명이 같은 MV, 공식 음원, 가사 영상은 같은 곡으로 보고, Live, Remix, Cover는 별도 버전으로 유지합니다. 검색이 일시적으로 실패하면 자동재생을 끄거나 음성 채널에서 나갈 때까지 간격을 두고 다시 시도합니다.

대기열 삭제 버튼을 누르면 곡 하나를 골라 삭제할 수 있습니다. 구간 삭제 버튼에서는 시작 곡과 끝 곡을 각각 선택해 양 끝을 포함한 구간 전체를 한 번에 삭제합니다. `/remove 2`처럼 번호로 한 곡을 삭제할 수도 있습니다. 대기열 관리 메시지는 마지막 삭제 30초 뒤, 메시지 신청의 곡 추가 확인은 10초 뒤 자동 삭제됩니다.

재생 중인 봇을 조작하거나 새 곡을 신청하려면 봇과 같은 음성 채널에 있어야 합니다. 봇이 재생 중일 때 다른 음성 채널의 요청으로 이동하지 않습니다.

전용 채널, 컨트롤 패널 메시지 ID, 자동재생 ON/OFF 설정은 `music_channels.json`에 서버별로 저장됩니다. 기존 채널 ID만 들어 있는 형식도 그대로 읽고, 다음 저장 때 새 형식으로 바뀝니다. 이 파일은 로컬 설정이라 Git에는 올리지 않도록 `.gitignore`에 넣어 두었습니다.

## 참고

- 음악 재생은 `yt-dlp`와 `FFmpeg`를 사용합니다.
- 곡명과 `auto` 시드는 동일한 YouTube Music 우선 검색을 사용합니다. 앨범·재생목록 텍스트는 기존 YouTube 재생목록 검색으로 처리합니다.
- 클라우드 서버 IP가 YouTube 자동화 확인에 걸리면 `YOUTUBE_COOKIES_FILE`로 쿠키 파일을 지정해야 할 수 있습니다.
- YouTube 쪽 변경으로 재생이 갑자기 실패하면 `python -m pip install --upgrade yt-dlp`로 업데이트해 보세요.
- 봇 토큰은 절대 GitHub나 채팅에 올리지 마세요.
