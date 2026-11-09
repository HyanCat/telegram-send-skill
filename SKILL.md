---
name: telegram-send
description: Send authorized text or UTF-8 Markdown attachments to a configured Telegram chat using a lightweight Linux CLI. Use when the user requests Telegram delivery or bot setup.
---

# Send a Telegram message or Markdown attachment

Use the included scripts on Linux with Python 3 and `/usr/bin/curl`. Each invocation makes at most one HTTPS request, runs on demand and requires no background service or third-party Python packages. It does not subscribe to task events or change existing bot/background rules.

## Configure

Use an existing compatible private configuration if the user has one. Otherwise have the user run `scripts/secure_config.py --config /path/to/private/target.conf` in their own interactive terminal and enter their bot token and numeric chat ID there. The bot must be allowed to message the chosen chat. The config directory must be owned by the user and private, and the file is created with mode 0600 without overwriting an existing file. Do not request credentials in chat, command arguments, logs, or repository files. Do not call `getUpdates` on a bot used by another service.

## Send

When the user has authorized sending the content to the configured chat, run the bundled CLI with an absolute path to the existing private config. Only the sending program may read it; never inspect or print credentials. Check that the intended recipient can access the source material and that the content, links and filename are suitable for that recipient. Configuration alone is not proof of access rights. Download Multica attachments only via the authenticated Multica CLI, then inspect the downloaded content before sending; do not fetch Multica resource URLs directly.

Prefer a detailed text message. When it exceeds the CLI's 3500 UTF-16 unit text limit, prepare a complete UTF-8 Markdown file and a concise summary. If the task already has a suitable Markdown attachment, reuse it after the same access/content checks. Do not silently truncate the result or automatically split it into multiple messages.

Existing text invocation remains compatible:

```sh
printf '%s' 'Message text' | python3 /path/to/telegram-send/scripts/telegram_send.py --config /path/to/private/target.conf
```

For a summary and attachment, send them together in **one** document message. The summary is a plain text caption (up to 1024 UTF-16 units); Markdown inside the file is uploaded intact, without Telegram Markdown parsing:

```sh
python3 /path/to/telegram-send/scripts/telegram_send.py --config /path/to/private/target.conf \
  --document /path/to/report.md < /path/to/summary.txt
```

For an attachment without a caption, use the same command with `</dev/null`. `--filename report.md` can override the outgoing basename. A document must be a nonempty regular UTF-8 file, contain no NUL, and be at most 20 MiB. Its outgoing name must end in `.md` or `.markdown`, be at most 128 UTF-8 bytes, and contain only letters, numbers, spaces, `.`, `_`, `-`, `(` or `)`; no leading dot or surrounding whitespace. Rename locally or use `--filename` when needed. Invalid or oversized input fails before sending; shorten the caption rather than sending a separate summary first.

Use stdin for content that should not appear in command arguments. Exit 0 means Telegram accepted the message for the configured chat (and returned a document receipt for an attachment); it does not prove the person read it. Exit 2 is a local validation error; exit 1 means Telegram rejected the request, curl could not start, or delivery is unknown, as stated in stderr. No response body, token or chat ID is printed.

Never automatically retry, including on rate limits, timeouts, interrupted responses or an unknown result: the whole document and caption may already have arrived. Verify in the chat before any manually authorized retry; do not use `getUpdates`. There is no multi-request partial success within an invocation. If separate earlier calls already sent a summary or another part, preserve those confirmed results and do not resend the whole set. Report exactly which calls were confirmed and which remain unknown. This CLI does not provide a persistent duplicate-send journal; do not start concurrent or repeated invocations for the same delivery.

See [README.md](README.md) or [README.zh-CN.md](README.zh-CN.md) for limits and isolated tests. Do not claim that an automatic notification integration exists merely because this CLI works.
