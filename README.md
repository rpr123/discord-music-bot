# Discord Music Bot

Python 기반 디스코드 음악 봇입니다. 슬래시 명령어로 제어할 수 있고, 음악 신청 전용 채널에서는 곡명이나 YouTube Music URL만 메시지로 보내도 바로 재생 대기열에 추가됩니다.

## 기능

- `/setupmusic` 음악 신청 전용 텍스트 채널 생성 또는 지정
- 전용 채널에 `아이유 좋은날`, `https://music.youtube.com/...`처럼 메시지만 보내서 재생
- 전용 채널에 `album: 앨범명`, `playlist: 플레이리스트명`처럼 보내서 통째로 추가
- 전용 채널에 `auto: 곡명`, `auto: 12 곡명`처럼 보내서 관련 곡 여러 개 추가
- 곡명 검색은 기본적으로 YouTube Music의 `songs` 섹션에서 가져오기
- YouTube Music 앨범/재생목록 링크를 보내면 여러 곡을 한 번에 대기열에 추가
- 지금 재생 중 카드에서 다음 곡 미리보기와 버튼으로 재생/일시정지, 스킵, 정지, 반복, 셔플, 대기열 확인
- 일반 `youtube.com/watch` 링크는 기본 설정에서 거부
- `/join` 현재 음성 채널에 입장
- `/play` YouTube Music URL 또는 검색어로 곡 재생/대기열 추가
- `/playalbum` YouTube Music 앨범 검색 또는 앨범 URL을 통째로 추가
- `/playplaylist` YouTube Music 재생목록 검색 또는 재생목록 URL을 통째로 추가
- `/playauto` 관련 곡 여러 개를 대기열에 추가
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
3. Discord Developer Portal에서 만든 봇 토큰

봇 권한은 서버 초대 URL을 만들 때 `applications.commands`, `bot`, `Connect`, `Speak`, `Use Voice Activity`, `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Manage Channels`, `Manage Messages`를 포함하세요.

초대 권한이 있어도 채널이나 카테고리 권한에서 봇 역할이 막혀 있으면 `Missing Permissions` 오류가 납니다. 음악 신청 채널과 명령어를 사용하는 채널에서 봇 역할에 `View Channel`, `Send Messages`, `Embed Links`, `Read Message History`, `Manage Messages`가 허용되어 있는지 확인하세요.

전용 채널에 보낸 곡명을 읽으려면 Discord Developer Portal의 봇 설정에서 `Message Content Intent`를 켜야 합니다.

## 설치

```powershell
cd C:\Users\정동환\Documents\Codex\discord-music-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
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

YouTube Music 검색은 기본으로 켜져 있습니다.

```env
MUSIC_CHANNEL_SILENT=true
MUSIC_CHANNEL_DELETE_REQUESTS=true
MUSIC_FEEDBACK_DELETE_SECONDS=10
YOUTUBE_MUSIC_ONLY=true
YOUTUBE_SEARCH_FALLBACK=true
YOUTUBE_MUSIC_SECTION=songs
MAX_BULK_TRACKS=50
DEFAULT_AUTO_TRACKS=8
MAX_AUTO_TRACKS=25
BOT_VOLUME=0.2
```

`MUSIC_CHANNEL_SILENT=true`이면 음악 신청 전용 채널에서 봇이 보내는 검색/대기열/Now playing 메시지를 조용한 메시지로 보냅니다. 사용자가 직접 보낸 곡 신청 메시지의 알림이나 각자의 채널 음소거 상태는 디스코드 클라이언트 설정 영역이라 봇이 강제로 바꿀 수 없습니다.

`MUSIC_CHANNEL_DELETE_REQUESTS=true`이면 전용 채널에서 사용자가 보낸 곡 신청 메시지를 재생/대기열 추가 성공 후 삭제합니다.

`MUSIC_FEEDBACK_DELETE_SECONDS=10`이면 메시지로 곡을 신청했을 때 나오는 임시 추가 확인 메시지를 10초 뒤 삭제합니다. 슬래시 명령어 응답은 기존처럼 신청자에게만 보입니다.

`YOUTUBE_SEARCH_FALLBACK=true`이면 YouTube Music 곡 검색이 빈 결과를 줄 때 일반 YouTube 검색을 한 번 더 시도합니다. 앨범/재생목록 검색은 YouTube Music 섹션 검색을 유지합니다.

`YOUTUBE_MUSIC_SECTION`은 `songs`, `videos`, `albums`, `artists`, `community playlists`, `featured playlists` 중에서 선택할 수 있습니다. 일반적인 음악 봇이면 `songs`가 가장 안정적입니다.

`MAX_BULK_TRACKS`는 앨범이나 재생목록을 한 번에 추가할 때 최대 몇 곡까지 대기열에 넣을지 정합니다.

`DEFAULT_AUTO_TRACKS`와 `MAX_AUTO_TRACKS`는 `auto:` 또는 `/playauto`로 관련 곡을 추가할 때의 기본/최대 개수입니다.

`BOT_VOLUME`은 봇이 서버에 내보내는 기본 출력 음량입니다. `1.0`이 디스코드 사용자 음량 기준 `100` 정도라고 보면 되고, `0.2`는 `20` 정도의 낮은 시작값입니다. 디스코드 봇은 사용자별 음량을 강제로 설정할 수 없어서, 이후 개인별 조절은 각 사용자가 디스코드에서 봇을 우클릭해 사용자 음량을 바꾸면 됩니다.

## 실행

```powershell
python bot.py
```

봇을 서버에 초대한 뒤 아래 순서로 사용하세요.

1. 관리 권한이 있는 사용자가 `/setupmusic`을 실행합니다.
2. 새로 만들어진 `#music` 채널 또는 지정한 채널에 들어갑니다.
3. 음성 채널에 들어간 상태로 전용 채널에 곡명이나 YouTube Music URL을 메시지로 보냅니다.

전용 채널 입력 예시:

```text
아이유 좋은날
album: NewJeans Get Up
playlist: lofi beats
auto: back number
auto: 12 lofi chill
https://music.youtube.com/playlist?list=...
```

곡이 시작되면 전용 채널에 “지금 재생 중” 카드가 표시됩니다. 카드에는 다음 곡이 함께 표시되고, 버튼으로 바로 재생/일시정지, 스킵, 정지, 반복, 셔플, 대기열 확인을 할 수 있습니다. 대기열 버튼을 누르면 삭제할 곡을 선택할 수 있고, `/remove 2`처럼 번호로도 삭제할 수 있습니다. 메시지 신청의 곡 추가 확인은 10초 뒤 자동 삭제되고, 모든 곡이 끝나거나 정지하면 이 카드는 자동으로 삭제됩니다.

전용 채널 설정은 `music_channels.json`에 서버별로 저장됩니다. 이 파일은 로컬 설정이라 Git에는 올리지 않도록 `.gitignore`에 넣어 두었습니다.

## 참고

- 음악 재생은 `yt-dlp`와 `FFmpeg`를 사용합니다.
- YouTube Music 검색은 `yt-dlp`의 `music.youtube.com/search` 처리 기능을 먼저 사용하고, 곡명 검색이 비어 있으면 `ytsearch` fallback을 사용할 수 있습니다.
- YouTube 쪽 변경으로 재생이 갑자기 실패하면 `python -m pip install --upgrade yt-dlp`로 업데이트해 보세요.
- 봇 토큰은 절대 GitHub나 채팅에 올리지 마세요.
