# Naver WORKS Mail MCP Server

Python MCP server for reading Naver WORKS mail through IMAP.

This server is read-only. It exposes MCP tools for listing folders, reading recent
message headers, and reading only new messages since the last checkpoint.

## Features

- Read Naver WORKS mail over IMAP SSL.
- List mail folders.
- Read messages from a specific folder.
- Remember the last read IMAP UID per folder for scheduled reads.
- Track IMAP `UIDVALIDITY` to avoid trusting stale checkpoints after folder reset.
- Store local read state in `.nworks_mail_state.json` by default.

## Requirements

- Python 3.12 or newer
- `uv`
- Naver WORKS mail address
- Naver WORKS app password or IMAP password
- Claude Desktop or another MCP-compatible client

## Environment Variables

Required:

| Name | Description |
| --- | --- |
| `NWORKS_MAIL_ADDRESS` | Naver WORKS mail address |
| `NWORKS_APP_PASSWORD` | Naver WORKS app password |

Optional:

| Name | Default | Description |
| --- | --- | --- |
| `NWORKS_IMAP_HOST` | `imap.worksmobile.com` | IMAP host |
| `NWORKS_IMAP_PORT` | `993` | IMAP SSL port |
| `NWORKS_STATE_PATH` | `.nworks_mail_state.json` | Local checkpoint file path |

## Claude Desktop Configuration

Use this when running directly from GitHub:

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

For local development:

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

Restart Claude Desktop after changing the MCP configuration.

## MCP Tools

| Tool | Description |
| --- | --- |
| `list_folders` | List available IMAP folders |
| `read_messages` | Read recent message headers from a folder |
| `read_new_messages` | Read only messages newer than the saved checkpoint |

`read_new_messages` is intended for scheduled use. Call it repeatedly with the
same folder name and it will continue from the last saved UID when the folder
`UIDVALIDITY` is unchanged.

## Development

Install dependencies and run tests:

```powershell
uv sync
uv run python -m unittest discover -s tests -v
```

Run import/compile checks:

```powershell
uv run python -m compileall src tests
uv run python -c "from nworks_mail_mcp.server import main; print('server import ok')"
```

## Security Notes

- Do not commit real mail addresses, passwords, app passwords, Claude config
  files, `.env` files, or `.nworks_mail_state.json`.
- If a password or app password is accidentally pushed to GitHub, revoke it and
  create a new one.
- This server reads mail headers only: UID, subject, sender, and date.
