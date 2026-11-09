"""Single-request transport. Importing never sends. workflow.py owns approval/journal."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import signal

CURL = "/usr/bin/curl"
API = "https://api.telegram.org"
REQUIRED_SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL


def load_target(path):
    path = Path(path).absolute()
    try:
        if path.resolve() != path or path.parent.stat().st_mode & 0o077:
            raise ValueError("PRIVATE_CONFIG_REQUIRED")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("PRIVATE_CONFIG_REQUIRED")
            raw = handle.read(4097)
        match = re.fullmatch(rb"tgram://([0-9]+:[A-Za-z0-9_-]+)/(-?[1-9][0-9]*)/\?detect=no&preview=no&image=no&album=no&format=text&overflow=upstream&verify=yes&redirect=no&cto=5&rto=30\n", raw)
        if len(raw) > 4096 or not match:
            raise ValueError("PRIVATE_CONFIG_REQUIRED")
        return {"token": match[1].decode(), "chat_id": int(match[2]), "fingerprint": hashlib.sha256(raw).hexdigest()}
    except (OSError, UnicodeError):
        raise ValueError("PRIVATE_CONFIG_REQUIRED") from None


def quoted(value):
    if any(c in value for c in "\r\n\0"):
        raise ValueError("CONFIG_REJECTED")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@contextmanager
def sealed(data=None, source=None):
    descriptor = os.memfd_create("approved-part", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        with os.fdopen(os.dup(descriptor), "wb") as output:
            if data is not None:
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError("PART_TOO_LARGE")
                output.write(data)
            else:
                total = 0
                with open(source, "rb") as input_file:
                    while chunk := input_file.read(65536):
                        total += len(chunk)
                        if total > 20 * 1024 * 1024:
                            raise ValueError("PART_TOO_LARGE")
                        output.write(chunk)
            output.flush()
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        yield descriptor
    finally:
        os.close(descriptor)


def request_config(target, kind, descriptor):
    token, chat = target["token"], target["chat_id"]
    if (not isinstance(token, str) or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token)
            or type(chat) is not int or not chat or abs(chat) >= 2**53):
        raise ValueError("TARGET_REJECTED")
    if kind not in {"text", "document"} or type(descriptor) is not int or descriptor < 0:
        raise ValueError("REQUEST_REJECTED")
    method = "sendMessage" if kind == "text" else "sendDocument"
    lines = ["silent", "globoff", "request = POST", "proto = \"=https\"", "proxy = \"\"",
             "connect-timeout = 5", "max-time = 30", "retry = 0", "max-redirs = 0",
             "max-filesize = 65536", 'header = "Expect:"',
             "url = " + quoted(API + "/bot" + token + "/" + method),
             'write-out = "\\nHTTP_STATUS:%{http_code}"']
    if kind == "text":
        lines += ['header = "Content-Type: application/json"',
                  "data-binary = " + quoted(f"@/proc/self/fd/{descriptor}")]
    else:
        lines += ["form-string = " + quoted(f"chat_id={chat}"),
                  "form = " + quoted(f"document=@/proc/self/fd/{descriptor};filename=approved-document.bin;type=application/octet-stream")]
    return ("\n".join(lines) + "\n").encode()


def parse_result(code, stdout, expected_chat):
    # Never use stderr, URL, description or response body in the returned summary.
    try:
        body, status = stdout.rsplit(b"\nHTTP_STATUS:", 1)
        http = int(status)
        data = json.loads(body)
        if (code == 0 and http == 200 and data.get("ok") is True
                and type(data["result"]["message_id"]) is int and data["result"]["message_id"] > 0
                and type(data["result"]["chat"]["id"]) is int
                and data["result"]["chat"]["id"] == expected_chat):
            return {"state": "sent", "http_status": http, "message_id": data["result"]["message_id"]}
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return {"state": "unknown"}


def invoke(config, descriptor, expected_chat):
    process = None
    try:
        process = subprocess.Popen([CURL, "--disable", "--config", "-"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                   pass_fds=(descriptor,), start_new_session=True)
        stdout, _ = process.communicate(config, timeout=35)
        return parse_result(process.returncode, stdout, expected_chat)
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unknown"}
    finally:
        # This process group is created here and contains only this curl invocation.
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()


def send_sealed(target, kind, descriptor, runner=None):
    """Only transport; caller must validate grant, receipt, target hash and journal."""
    try:
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) & REQUIRED_SEALS != REQUIRED_SEALS:
            raise ValueError("SEALED_PART_REQUIRED")
        size = os.fstat(descriptor).st_size
        if size > (32768 if kind == "text" else 20 * 1024 * 1024):
            raise ValueError("PART_TOO_LARGE")
        if kind == "text":
            body = json.loads(os.pread(descriptor, size, 0))
            if (not isinstance(body, dict) or set(body) - {"chat_id", "text", "link_preview_options"}
                    or type(body.get("chat_id")) is not int or body["chat_id"] != target["chat_id"]
                    or body.get("link_preview_options") != {"is_disabled": True}):
                raise ValueError("TEXT_TARGET_MISMATCH")
            if (not isinstance(body.get("text"), str) or not body["text"]
                    or len(body["text"].encode("utf-16-le")) // 2 > 3500):
                raise ValueError("TEXT_LIMIT")
        return (runner or invoke)(request_config(target, kind, descriptor), descriptor, target["chat_id"])
    except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ValueError("PART_REJECTED") from None
