# Naver WORKS Mail MCP 서버

IMAP을 통해 Naver WORKS 메일을 읽는 Python MCP 서버입니다.

이 서버는 읽기 전용입니다. 메일 폴더 목록 조회, 최근 메시지 헤더 조회,
마지막 체크포인트 이후 새 메시지 조회를 위한 MCP 도구를 제공합니다.

## 주요 기능

- IMAP SSL로 Naver WORKS 메일을 읽습니다.
- 메일 폴더 목록을 조회합니다.
- 특정 폴더의 메시지를 읽습니다.
- 예약 조회를 위해 폴더별 마지막으로 읽은 IMAP UID를 기억합니다.
- 폴더가 초기화된 뒤 오래된 체크포인트를 신뢰하지 않도록 IMAP `UIDVALIDITY`를 추적합니다.
- 기본적으로 `.nworks_mail_state.json`에 로컬 읽기 상태를 저장합니다.

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

`read_new_messages`는 예약 실행을 위한 도구입니다. 같은 폴더 이름으로 반복 호출하면
폴더 `UIDVALIDITY`가 바뀌지 않는 한 마지막으로 저장된 UID부터 이어서 읽습니다.

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
- 이 서버는 UID, 제목, 보낸 사람, 날짜로 구성된 메일 헤더만 읽습니다.
