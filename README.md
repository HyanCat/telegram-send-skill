# Telegram Send

Send text or UTF-8 Markdown documents to a Telegram bot chat using a small on-demand CLI and an agent skill. Requires Linux, Python 3 and `/usr/bin/curl`; it does not install a service or Python packages.

Install as a Codex skill, then restart your agent session:

```sh
git clone https://github.com/HyanCat/telegram-send-skill.git ~/.codex/skills/telegram-send
cd ~/.codex/skills/telegram-send
```

The repository root is the skill directory; other agents that support `SKILL.md` can copy or clone it to their skills directory.

Create a private configuration from your own terminal:

```sh
python3 scripts/secure_config.py --config ~/.config/telegram-send/target.conf
```

Enter the bot token and numeric chat ID at the prompts. The bot must already be able to send to the chat. The script creates a private config and does not overwrite one. Keep the token and config out of version control and logs.

Send a message:

```sh
printf '%s' 'Hello from Telegram Send' | python3 scripts/telegram_send.py --config ~/.config/telegram-send/target.conf
```

Only a verified Telegram API success is reported as sent. If delivery is unconfirmed, check the chat before retrying. This CLI does not set up automatic event triggers.

Send a Markdown file with an optional summary (stdin supplies the caption):

```sh
python3 scripts/telegram_send.py --config /path/to/private/target.conf \
  --document /path/to/report.md < /path/to/summary.txt
```

Use `</dev/null` for no caption. The existing positional message still works; with `--document` it becomes the caption. `--filename report.md` overrides the outgoing basename without exposing local directories. Authorize the recipient and check the file's content, name and source access before sending. Obtain Multica attachments using its authenticated CLI only. The program reads the existing private config; do not open it, log it, or pass credentials through arguments or environment variables.

| Input | CLI limit |
| --- | --- |
| Text | 1–3500 UTF-16 units (existing conservative limit) |
| Document caption | 0–1024 UTF-16 units, plain text |
| File | Nonempty regular UTF-8 file, no NUL, at most 20 MiB; no final symlink/FIFO/device |
| Outgoing basename | `.md` or `.markdown`, up to 128 UTF-8 bytes; letters, numbers, spaces and `._()-` only; no leading dot or surrounding whitespace |

The official API allows [4096 text characters](https://core.telegram.org/bots/api#sendmessage), [1024 caption characters and files up to 50 MB](https://core.telegram.org/bots/api#senddocument). This CLI retains its smaller text/file caps and counts UTF-16 units conservatively (an emoji may count as two). It sends file bytes with multipart `sendDocument`, MIME `text/markdown`, content type detection disabled, and no parse mode. Validation and upload use the same sealed in-memory snapshot. No truncation, text splitting or automatic fallback occurs.

One invocation sends one message: the document and caption share a single request. Exit 0 means an accepted API receipt for the configured chat, not proof of human reading. Exit 2 means local validation failed. Exit 1 reports a verified client rejection, an unstartable curl, or an **unknown** result. A timeout, disconnect, invalid response, server error or mismatched chat is unknown and may already have delivered; never automatically retry or send a fallback. A verified HTTP 4xx API rejection is reported without its potentially sensitive description. If earlier separate calls succeeded, keep their receipts and do not resend those parts; check the chat before any manually authorized retry of an unknown call. No persistent deduplication is provided. Do not use `getUpdates` to verify delivery or change existing bot/background rules.

Run isolated tests (Python standard library, Linux, curl and OpenSSL):

```sh
python3 -I -m unittest discover -s scripts -p 'test_*.py' -v
```

Tests create synthetic configs/files, mock fault paths, and use real curl against an ephemeral HTTPS server on `127.0.0.1`. They never load a user's config or contact Telegram. A real Telegram document delivery remains a separate, explicitly authorized validation step.
