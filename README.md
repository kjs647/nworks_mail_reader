# Naver WORKS Mail MCP 서버

IMAP을 통해 Naver WORKS 메일을 읽는 Python MCP 서버입니다.

이 서버는 읽기 전용입니다. 메일 폴더 목록 조회, 최근 메시지 헤더 조회,
마지막 체크포인트 이후 새 메시지 조회, UID 기반 본문 조회, 본문 키워드 검색, SQLite
인덱스 기반 문맥 검색 후보 조회를 위한 MCP 도구를 제공합니다.

## 주요 기능

- IMAP SSL로 Naver WORKS 메일을 읽습니다.
- 메일 폴더 목록을 조회합니다.
- 특정 폴더의 메시지 헤더를 읽습니다.
- UID로 특정 메일 본문을 읽습니다.
- 최근 메일 본문에서 키워드를 검색합니다.
- SQLite FTS 인덱스로 메일 검색 후보를 빠르게 찾습니다.
- 주민등록번호, 토큰, 비밀번호 같은 민감값을 MCP 응답에서 마스킹합니다.
- 제목에 보상 관련 단어가 포함된 메일은 기본적으로 본문을 읽지 않습니다.
- 예약 조회를 위해 폴더별 마지막으로 읽은 IMAP UID를 기억합니다.
- 폴더가 초기화된 뒤 오래된 체크포인트를 신뢰하지 않도록 IMAP `UIDVALIDITY`를 추적합니다.
- 기본적으로 `.nworks_mail_state.json`에 로컬 읽기 상태를 저장합니다.
- 기본적으로 `.nworks_mail_index.sqlite`에 검색 인덱스를 저장합니다.

## 요구 사항

- Python 3.12 이상
- `uv`
- Naver WORKS 메일 주소
- Naver WORKS 앱 비밀번호 또는 IMAP 비밀번호
- Claude Desktop 또는 MCP 호환 클라이언트

## 환경 변수

필수:

| 이름 | 설명 |
| --- | --- |
| `NWORKS_MAIL_ADDRESS` | Naver WORKS 메일 주소 |
| `NWORKS_APP_PASSWORD` | Naver WORKS 앱 비밀번호 |

선택:

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `NWORKS_IMAP_HOST` | `imap.worksmobile.com` | IMAP 호스트 |
| `NWORKS_IMAP_PORT` | `993` | IMAP SSL 포트 |
| `NWORKS_STATE_PATH` | `.nworks_mail_state.json` | 로컬 체크포인트 파일 경로 |
| `NWORKS_INDEX_PATH` | `.nworks_mail_index.sqlite` | SQLite 검색 인덱스 파일 경로 |
| `NWORKS_REDACTION_EXTRA_PATTERNS_JSON` | 없음 | 추가 마스킹 정규식 JSON 배열 |

## Claude Desktop 설정

GitHub에서 바로 실행할 때는 아래 설정을 사용합니다.

```json
{
  "mcpServers": {
    "nworks-mail": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/kjs647/nworks_mail_reader.git",
        "nmail-reader"
      ],
      "env": {
        "NWORKS_MAIL_ADDRESS": "your-email@example.com",
        "NWORKS_APP_PASSWORD": "your-app-password"
      }
    }
  }
}
```

로컬 개발 환경에서는 아래 설정을 사용합니다.

```json
{
  "mcpServers": {
    "nworks-mail": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\nmail_reader",
        "run",
        "nmail-reader"
      ],
      "env": {
        "NWORKS_MAIL_ADDRESS": "your-email@example.com",
        "NWORKS_APP_PASSWORD": "your-app-password"
      }
    }
  }
}
```

MCP 설정을 변경한 뒤에는 Claude Desktop을 다시 시작하세요.

## MCP 도구

| 도구 | 설명 |
| --- | --- |
| `list_folders` | 사용 가능한 IMAP 폴더 목록을 조회합니다. |
| `read_messages` | 폴더의 최근 메시지 헤더를 읽습니다. |
| `read_new_messages` | 저장된 체크포인트보다 새 메시지만 읽습니다. |
| `read_message_body` | 폴더와 UID로 특정 메시지 본문을 읽습니다. |
| `search_messages_by_body` | 최근 메시지 본문에서 키워드가 포함된 메시지를 찾습니다. |
| `sync_mail_index` | SQLite 검색 인덱스를 초기/증분 동기화합니다. |
| `search_messages_context` | SQLite 인덱스에서 AI가 읽을 검색 후보를 빠르게 반환합니다. |

`read_new_messages`는 예약 실행을 위한 도구입니다. 같은 폴더 이름으로 반복 호출하면
폴더 `UIDVALIDITY`가 바뀌지 않는 한 마지막으로 저장된 UID부터 이어서 읽습니다.

`read_message_body`는 `read_messages` 또는 `read_new_messages`가 반환한 `uid`를 사용합니다.
기본적으로 최대 20,000자까지 본문을 반환하며, 초과하면 `truncated`가 `true`입니다.
본문은 `text/plain`을 우선 사용하고, plain 본문이 없으면 `text/html`을 간단히 텍스트로 변환합니다.
첨부파일 파트는 본문에서 제외합니다.

`read_messages`와 `read_new_messages`는 제목에 `연봉`, `성과급`, `보너스`, `인센티브`,
`보상`, `급여`, `임금`이 포함된 메시지에 `body_read_blocked: true`와
`block_reason: "COMPENSATION_SUBJECT"`를 표시합니다. 이런 메시지는 `read_message_body`가
기본적으로 본문을 가져오지 않고 `body: "[BLOCKED:COMPENSATION_SUBJECT]"`를 반환합니다.
사용자가 목록을 확인한 뒤 본문 읽기를 명시적으로 허용하려면 `read_message_body`에
`allow_blocked_body: true`를 전달합니다. 예약 실행이나 루틴 호출은 기본값을 사용하므로
차단된 본문을 읽지 않습니다.

`search_messages_by_body`는 최근 UID부터 기본 200개까지 본문을 스캔해 대소문자 구분 없이
`query`가 포함된 메일을 반환합니다. 검색 결과의 본문은 기본 2,000자로 제한됩니다.
메일함이 크면 `max_scan`을 필요한 범위로 조절하세요. 기본적으로 보상 관련 제목의
메일은 본문 검색 대상에서도 제외됩니다. 사용자가 명시적으로 허용하려면
`allow_blocked_body: true`를 전달합니다.

`sync_mail_index`는 기본적으로 최근 2,000개 메일부터 SQLite 인덱스를 만들고, 이후 호출에서는
새 UID를 최대 100개씩 증분 동기화합니다. `full_check: true`를 전달하면 IMAP의 현재 UID
목록과 비교해 삭제되거나 이동된 메일을 즉시 정리합니다. 자동 삭제 검사는 하루 1회 수행됩니다.

`search_messages_context`는 검색 전에 새 메일을 최대 100개까지 동기화한 뒤 SQLite FTS
인덱스에서 기본 상위 20개 후보를 반환합니다. 응답에는 `uid`, `folder`, `subject`,
`sender`, `date`, `excerpt`, `score`, `body_index_blocked`, `block_reason`이 포함됩니다.
동기화가 실패해도 기존 인덱스가 있으면 검색을 계속하고 `sync.ok: false`와 오류 메시지를
함께 반환합니다. 서버 내부에서 LLM이나 임베딩 API를 호출하지 않으며, MCP 클라이언트의 AI가
반환된 후보를 읽고 문맥 판단을 수행합니다.

SQLite 인덱스에는 검색 품질을 위해 마스킹 전 추출 텍스트 본문을 저장합니다. 첨부파일,
이미지, 원본 MIME 전체, base64 원문은 저장하지 않습니다. MCP 응답에는 기존 마스킹 정책을
항상 적용합니다. 보상 관련 제목의 메일은 기본적으로 본문을 가져오거나 SQLite에 저장하지
않고, 제목/발신자/날짜와 `body_index_blocked: true`만 기록합니다. 본문 색인이 꼭 필요하면
`sync_mail_index`에 `allow_blocked_body: true`를 명시적으로 전달해야 합니다.

## 마스킹 정책

MCP 응답으로 반환되는 제목, 발신자, 본문에는 기본 마스킹이 적용됩니다. 기본 대상은
주민등록번호 형식, JWT, `Authorization: Bearer ...`, `access_token`, `refresh_token`,
`api_key`, `x-api-key`, `password`, `secret`, `private_key` 계열 key-value,
URL query의 `token`, `access_token`, `refresh_token`, `api_key`, `key`, `secret`입니다.
치환값은 `[REDACTED:<TYPE>]` 형식입니다.

이메일 주소와 전화번호는 기본 마스킹 대상이 아닙니다. 카드번호와 계좌번호도 오탐을
줄이기 위해 기본 대상에서 제외했습니다. 추가로 가리고 싶은 패턴은 JSON 배열로 설정합니다.

```json
["Project-[0-9]+", "CONFIDENTIAL-[A-Z]+"]
```

`search_messages_by_body`는 검색 매칭을 위해 원문 본문을 읽은 뒤 반환값만 마스킹합니다.
다만 보상 관련 제목은 기본적으로 본문을 읽지 않으므로 검색 대상에서 제외됩니다.

마스킹은 완전한 DLP가 아니라 MCP 응답과 자동 루틴에서 민감값 노출을 줄이는 방어 계층입니다.

## 개발

의존성을 설치하고 테스트를 실행합니다.

```powershell
uv sync
uv run python -m unittest discover -s tests -v
```

임포트/컴파일 검사를 실행합니다.

```powershell
uv run python -m compileall src tests
uv run python -c "from nworks_mail_mcp.server import main; print('server import ok')"
```

## 보안 참고 사항

- 실제 메일 주소, 비밀번호, 앱 비밀번호, Claude 설정 파일, `.env` 파일,
  `.nworks_mail_state.json`은 커밋하지 마세요.
- 비밀번호나 앱 비밀번호를 실수로 GitHub에 푸시했다면 즉시 폐기하고 새로 생성하세요.
- 이 서버는 사용자가 허용한 메일 본문을 MCP 응답으로 반환할 수 있으므로 민감한 메일 내용을
  신뢰하지 않는 클라이언트나 로그에 노출하지 않도록 주의하세요.
