"""Local human-only configuration writer. No network, stdout secrets, or argv secrets."""
import argparse
import configparser
import getpass
import os
from pathlib import Path
import re
import sys


def write_config(destination: Path, token: str, chat_id: str, kind="apprise") -> None:
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Invalid token syntax")
    if not re.fullmatch(r"-?[1-9][0-9]*", chat_id):
        raise ValueError("Numeric chat_id required")
    parent = destination.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Do not follow a linked parent or overwrite an existing configuration.
    if parent.resolve() != parent.absolute() or parent.stat().st_uid != os.getuid():
        raise ValueError("Config directory must be owned by this user and contain no symlink")
    if parent.stat().st_mode & 0o077:
        raise ValueError("Config directory must have mode 0700")
    if kind not in {"apprise", "telegram-send"}:
        raise ValueError("Unknown config kind")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        if kind == "apprise":
            handle.write(f"tgram://{token}/{chat_id}/?detect=no&preview=no&image=no&album=no"
                         "&format=text&overflow=upstream&verify=yes&redirect=no&cto=5&rto=30\n")
        else:
            config = configparser.ConfigParser(interpolation=None)
            config["telegram"] = {"token": token, "chat_id": chat_id}
            config.write(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--kind", choices=["apprise", "telegram-send"], default="apprise")
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error("Use a private interactive terminal; never paste credentials into an agent tool")
    token = getpass.getpass("Bot token (hidden): ").strip()
    chat_id = getpass.getpass("Verified numeric chat_id (hidden): ").strip()
    try:
        write_config(args.config.expanduser().absolute(), token, chat_id, args.kind)
    except (OSError, ValueError):
        print("Configuration refused. Check syntax, directory ownership/mode, and existing file.", file=sys.stderr)
        return 1
    finally:
        token = ""  # Python does not guarantee secure memory erasure.
    print("Wrote a new mode-0600 configuration. No network request was made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
