#!/usr/bin/env python3
"""Send one message to the Telegram chat in a private configuration file."""
import argparse
import json
import sys
from pathlib import Path

import curl_transport


def send_message(config, text, runner=None):
    if not isinstance(text, str) or not text or len(text.encode("utf-16-le")) // 2 > 3500:
        raise ValueError("MESSAGE_EMPTY_OR_TOO_LONG")
    target = curl_transport.load_target(config)
    body = json.dumps({"chat_id": target["chat_id"], "text": text,
                       "link_preview_options": {"is_disabled": True}},
                      ensure_ascii=False).encode("utf-8")
    with curl_transport.sealed(data=body) as descriptor:
        return curl_transport.send_sealed(target, "text", descriptor, runner=runner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="private configuration file")
    parser.add_argument("message", nargs="?", help="message; omit to read stdin")
    args = parser.parse_args()
    message = args.message if args.message is not None else sys.stdin.read(32769)
    try:
        result = send_message(args.config.expanduser(), message)
    except (OSError, ValueError):
        print("Could not send: check the private configuration and message length.", file=sys.stderr)
        return 2
    if result["state"] != "sent":
        print("Delivery unconfirmed. Check the chat before retrying.", file=sys.stderr)
        return 1
    print("Sent (message id: {}).".format(result["message_id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
