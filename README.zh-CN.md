# Telegram Send

通过轻量命令和 agent skill 向 Telegram 会话发送文字或 UTF-8 Markdown 附件。需要 Linux、Python 3 和 `/usr/bin/curl`；按需运行，不安装后台服务或额外 Python 包。

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

发送摘要和 Markdown 附件，标准输入用作文件说明：

```sh
python3 scripts/telegram_send.py --config /path/to/private/target.conf \
  --document /path/to/report.md < /path/to/summary.txt
```

只发附件时用 `</dev/null`。旧的位置参数仍可用；加上 `--document` 时，它表示文件说明。`--filename report.md` 可指定对外文件名，不暴露本地目录。发送者须先核对收件人有权访问来源、内容和文件名可向其披露；Multica 任务附件仅通过已认证的 CLI 下载后检查。私有配置仅由发送程序读取，勿查看、打印或将凭据放入参数、环境变量及日志。

| 输入 | 本 CLI 限制 |
| --- | --- |
| 文字 | 1–3500 个 UTF-16 单元，保留旧限制 |
| 文件说明 | 0–1024 个 UTF-16 单元，按纯文本发送 |
| 附件 | 非空普通 UTF-8 文件，无 NUL，最多 20 MiB；拒绝末级符号链接、FIFO、设备等 |
| 对外文件名 | `.md` 或 `.markdown`，最多 128 个 UTF-8 字节；只含字母、数字、空格和 `._()-`，不能以点开头或带首尾空白 |

Telegram 官方允许[文字 4096 字符](https://core.telegram.org/bots/api#sendmessage)、[文件说明 1024 字符、文件 50 MB](https://core.telegram.org/bots/api#senddocument)。本工具保留较小的文字和文件上限，并保守按 UTF-16 计数（部分 emoji 算两个单元）。附件通过 multipart `sendDocument` 原样上传，类型为 `text/markdown`，关闭类型探测，不设置 Markdown 解析模式。校验和上传使用同一份不可修改的内存快照。超限直接拒绝，不截断、不拆消息、不自动改用其他发送方式。

摘要与文件作为同一条文档消息发送，每次最多一个请求。退出码 0 表示 Telegram 已接受且回执会话匹配，附件还需有文档回执；不代表用户已阅读。退出码 2 表示本地校验失败。退出码 1 会区分明确拒绝、curl 无法启动或送达未知。超时、断连、响应损坏、服务端错误、会话不匹配都按未知处理，即使没有回执也可能已送达。明确 HTTP 4xx API 拒绝仅显示状态码，不输出可能包含隐私的响应说明。

所有失败均不自动重发。一次请求内部没有“摘要已发、附件失败”的两个发送阶段；如果此前通过独立调用已发送某些内容，应保留其已确认结果，不要整组重发。未知时先查看会话，明确获准后再人工决定重试，禁止通过 `getUpdates` 确认。工具不提供持久去重记录，勿并发或重复派发同一内容。也不修改现有机器人或后台规则。

隔离测试需要 Linux、Python 标准库、curl 和 OpenSSL：

```sh
python3 -I -m unittest discover -s scripts -p 'test_*.py' -v
```

测试仅创建合成配置和文件，模拟错误，并用真实 curl 连接 `127.0.0.1` 的临时 HTTPS 服务；不加载用户配置、不访问 Telegram。真实 Telegram 文件发送须另行获得确认并验证。
