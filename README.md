# Telegram Send

Send text to a Telegram bot chat using a small on-demand CLI and an agent skill. Requires Linux, Python 3 and `/usr/bin/curl`; it does not install a service or Python packages.

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
