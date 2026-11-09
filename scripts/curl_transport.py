"""Single-request transport. Importing never sends; callers own authorization."""
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
import unicodedata

CURL = "/usr/bin/curl"
API = "https://api.telegram.org"
REQUIRED_SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
DOCUMENT_LIMIT = 20 * 1024 * 1024
CAPTION_LIMIT = 1024


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
    if "\0" in value:
        raise ValueError("CONFIG_REJECTED")
    return ('"' + value.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"')


def document_metadata(filename, caption):
    # Restrict curl's form syntax and avoid leaking source directories in filenames.
    if (not isinstance(filename, str) or not filename or filename.startswith(".")
            or filename != filename.strip() or len(filename.encode("utf-8")) > 128
            or not filename.lower().endswith((".md", ".markdown"))
            or not all(c.isalnum() or c in " ._()-" for c in filename)
            or any(unicodedata.category(c).startswith("C") for c in filename)):
        raise ValueError("DOCUMENT_FILENAME_REJECTED")
    if (not isinstance(caption, str) or "\0" in caption
            or len(caption.encode("utf-16-le")) // 2 > CAPTION_LIMIT):
        raise ValueError("CAPTION_TOO_LONG_OR_INVALID")


@contextmanager
def sealed(data=None, source=None):
    descriptor = os.memfd_create("approved-part", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        with os.fdopen(os.dup(descriptor), "wb") as output:
            if data is not None:
                if len(data) > DOCUMENT_LIMIT:
                    raise ValueError("PART_TOO_LARGE")
                output.write(data)
            else:
                total = 0
                source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(source_fd, "rb") as input_file:
                    if not stat.S_ISREG(os.fstat(input_file.fileno()).st_mode):
                        raise ValueError("REGULAR_DOCUMENT_REQUIRED")
                    while chunk := input_file.read(65536):
                        total += len(chunk)
                        if total > DOCUMENT_LIMIT:
                            raise ValueError("PART_TOO_LARGE")
                        output.write(chunk)
            output.flush()
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        yield descriptor
    finally:
        os.close(descriptor)


def request_config(target, kind, descriptor, *, filename="document.md", caption=""):
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
        document_metadata(filename, caption)
        lines += ["form-string = " + quoted(f"chat_id={chat}"),
                  "form = " + quoted(f"document=@/proc/self/fd/{descriptor};filename={filename};type=text/markdown"),
                  "form-string = " + quoted("disable_content_type_detection=true")]
        if caption:
            lines += ["form-string = " + quoted("caption=" + caption)]
    return ("\n".join(lines) + "\n").encode()


def parse_result(code, stdout, expected_chat, *, kind="text"):
    # Never use stderr, URL, description or response body in the returned summary.
    try:
        body, status = stdout.rsplit(b"\nHTTP_STATUS:", 1)
        http = int(status)
        data = json.loads(body)
        if (code == 0 and http == 200 and data.get("ok") is True
                and type(data["result"]["message_id"]) is int and data["result"]["message_id"] > 0
                and type(data["result"]["chat"]["id"]) is int
                and data["result"]["chat"]["id"] == expected_chat
                and (kind != "document" or (
                    isinstance(data["result"]["document"]["file_id"], str)
                    and data["result"]["document"]["file_id"]))):
            return {"state": "sent", "http_status": http, "message_id": data["result"]["message_id"]}
        if (code == 0 and 400 <= http < 500 and data.get("ok") is False
                and type(data.get("error_code")) is int and data["error_code"] == http):
            return {"state": "rejected", "http_status": http, "error_code": http}
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return {"state": "unknown"}


def invoke(config, descriptor, expected_chat, *, kind="text"):
    process = None
    try:
        process = subprocess.Popen([CURL, "--disable", "--config", "-"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                   pass_fds=(descriptor,), start_new_session=True)
        stdout, _ = process.communicate(config, timeout=35)
        return parse_result(process.returncode, stdout, expected_chat, kind=kind)
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "not_sent" if process is None else "unknown"}
    finally:
        # This process group is created here and contains only this curl invocation.
        if process is not None and process.poll() is None:
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                # Cleanup cannot turn an attempted request into a preflight error.
                pass


def send_sealed(target, kind, descriptor, runner=None, *, filename="document.md", caption=""):
    """Only transport; caller must authorize content and the configured recipient."""
    try:
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) & REQUIRED_SEALS != REQUIRED_SEALS:
            raise ValueError("SEALED_PART_REQUIRED")
        size = os.fstat(descriptor).st_size
        if size > (32768 if kind == "text" else DOCUMENT_LIMIT):
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
        elif kind == "document":
            document_metadata(filename, caption)
            if not size:
                raise ValueError("DOCUMENT_EMPTY")
            text = os.pread(descriptor, size, 0).decode("utf-8")
            if "\0" in text:
                raise ValueError("DOCUMENT_UTF8_REQUIRED")
        config = request_config(target, kind, descriptor, filename=filename, caption=caption)
        if runner is not None:
            return runner(config, descriptor, target["chat_id"])
        return invoke(config, descriptor, target["chat_id"], kind=kind)
    except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ValueError("PART_REJECTED") from None
