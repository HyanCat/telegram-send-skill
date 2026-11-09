---
name: telegram-send
description: Send a requested message to a configured Telegram chat using a lightweight Linux CLI. Use when the user asks to send a Telegram message or set up a bot for this purpose.
---

# Send a Telegram message

Use the included scripts on Linux with Python 3 and `/usr/bin/curl`. They make one HTTPS request, run on demand and require no background service or third-party Python packages. This skill sends text; it does not automatically subscribe to task events.

## Configure

Use an existing compatible private configuration if the user has one. Otherwise have the user run `scripts/secure_config.py --config /path/to/private/target.conf` in their own interactive terminal and enter their bot token and numeric chat ID there. The bot must be allowed to message the chosen chat. The config directory must be owned by the user and private, and the file is created with mode 0600 without overwriting an existing file. Do not request credentials in chat, command arguments, logs, or repository files. Do not call `getUpdates` on a bot used by another service.

## Send

When the user has authorized sending the content to the configured chat, run the bundled CLI with an absolute path to the config:

```sh
printf '%s' 'Message text' | python3 /path/to/telegram-send/scripts/telegram_send.py --config /path/to/private/target.conf
```

Use stdin for message content when it should not appear in command arguments. Never print the config file. The CLI reports success only after Telegram returns an accepted message for the configured chat. An unconfirmed result may mean the message was delivered; check before retrying instead of automatically resending. Report delivery accurately, and do not claim that an automatic notification integration exists merely because this CLI works.
