#!/usr/bin/env python3
"""Send text or a UTF-8 Markdown document to a privately configured Telegram chat."""
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


def send_document(config, document, caption="", runner=None, *, filename=None):
    document = Path(document)
    filename = document.name if filename is None else filename
    curl_transport.document_metadata(filename, caption)
    # Snapshot once; validation and upload use the same immutable bytes.
    with curl_transport.sealed(source=document) as descriptor:
        target = curl_transport.load_target(config)
        return curl_transport.send_sealed(target, "document", descriptor, runner=runner,
                                          filename=filename, caption=caption)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="private configuration file")
    parser.add_argument("message", nargs="?", help="text or document caption; omit to read stdin")
    parser.add_argument("--document", type=Path, help="UTF-8 Markdown file (at most 20 MiB)")
    parser.add_argument("--filename", help="optional outgoing .md/.markdown basename (requires --document)")
    args = parser.parse_args()
    if args.filename is not None and args.document is None:
        parser.error("--filename requires --document")
    try:
        message = args.message
        if message is None:
            message = "" if args.document and sys.stdin.isatty() else sys.stdin.read(32769)
        if args.document is not None:
            result = send_document(args.config.expanduser(), args.document.expanduser(), message,
                                   filename=args.filename)
        else:
            result = send_message(args.config.expanduser(), message)
    except (OSError, ValueError):
        print("Nothing sent: check the private configuration; text must be 1-3500 UTF-16 units. "
              "Documents must be nonempty regular UTF-8 files up to 20 MiB, with a safe "
              ".md/.markdown filename up to 128 UTF-8 bytes and a caption up to 1024 UTF-16 units.",
              file=sys.stderr)
        return 2
    if result["state"] == "rejected":
        print("Telegram rejected the request (HTTP {}). Nothing accepted; no retry was made."
              .format(result["http_status"]), file=sys.stderr)
        return 1
    if result["state"] == "not_sent":
        print("Request could not start. Nothing sent; check /usr/bin/curl.", file=sys.stderr)
        return 1
    if result["state"] != "sent":
        print("Delivery unconfirmed; the message or document may already be delivered. "
              "Check the chat before any manually authorized retry. No retry was made.", file=sys.stderr)
        return 1
    label = "Sent document" if args.document is not None else "Sent"
    print("{} (message id: {}).".format(label, result["message_id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
