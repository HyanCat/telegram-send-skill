# Telegram Send

通过轻量命令和 agent skill 向 Telegram 会话发送文字。需要 Linux、Python 3 和 `/usr/bin/curl`；按需运行，不安装后台服务或额外 Python 包。

安装为 Codex skill，重启 agent 会话后即可发现：

```sh
git clone https://github.com/HyanCat/telegram-send-skill.git ~/.codex/skills/telegram-send
cd ~/.codex/skills/telegram-send
```

仓库根目录就是 skill 目录；其他支持 `SKILL.md` 的 agent 也可将其复制或克隆到对应的 skills 目录。

本人在私密终端创建配置：

```sh
python3 scripts/secure_config.py --config ~/.config/telegram-send/target.conf
```

根据提示输入 Bot token 和数字 chat ID。Bot 需要能向该会话发消息；脚本创建私有配置，不覆盖已有文件。不要将 token 和配置文件提交到仓库或写进日志。

发送消息：

```sh
printf '%s' '来自 Telegram Send 的消息' | python3 scripts/telegram_send.py --config ~/.config/telegram-send/target.conf
```

只有 Telegram 接口确认成功才报告已发送。若送达状态不明，请先查看会话再重试。该 CLI 不会自动配置任务事件触发。
