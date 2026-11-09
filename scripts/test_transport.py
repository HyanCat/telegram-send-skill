"""Offline transport checks and a real curl upload to a loopback HTTPS fixture."""
from email.parser import BytesParser
from email.policy import default
import http.server
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import curl_transport as transport
from secure_config import write_config
from telegram_send import send_document, send_message


def response(data, http=200):
    return json.dumps(data).encode() + b"\nHTTP_STATUS:" + str(http).encode()


def accepted(chat=100):
    return {"ok": True, "result": {"message_id": 42, "chat": {"id": chat},
                                   "document": {"file_id": "synthetic-file"}}}


class ParseTest(unittest.TestCase):
    def test_verified_text_and_document(self):
        for kind in ["text", "document"]:
            result = transport.parse_result(0, response(accepted()), 100, kind=kind)
            self.assertEqual(result, {"state": "sent", "http_status": 200, "message_id": 42})

    def test_explicit_client_rejection_has_no_description_or_chat(self):
        for http in [400, 401, 403, 413, 429]:
            data = {"ok": False, "error_code": http, "description": "PRIVATE RESPONSE"}
            self.assertEqual(transport.parse_result(0, response(data, http), 100),
                             {"state": "rejected", "http_status": http, "error_code": http})

    def test_ambiguous_results_are_unknown(self):
        bad = [b"", b"<html>gateway error</html>", response(accepted(-100)),
               response({"ok": True}), response({"ok": True, "result": {"message_id": True}}),
               response({"ok": False, "error_code": 500}, 500),
               response({"ok": False, "error_code": 403}, 401),
               response(accepted(), 302), response(accepted(), 201),
               b"\xff\nHTTP_STATUS:200"]
        for payload in bad:
            with self.subTest(payload=payload):
                self.assertEqual(transport.parse_result(0, payload, 100), {"state": "unknown"})
        for code in [1, 18, 28, 63]:
            self.assertEqual(transport.parse_result(code, response(accepted()), 100), {"state": "unknown"})

    def test_document_requires_a_document_receipt(self):
        data = accepted()
        del data["result"]["document"]
        self.assertEqual(transport.parse_result(0, response(data), 100, kind="document"),
                         {"state": "unknown"})


class InvokeTest(unittest.TestCase):
    def test_secrets_use_stdin_only_and_environment_is_clean(self):
        target = {"token": "1234:SECRET_SENTINEL", "chat_id": 100}
        with transport.sealed(data=b"# synthetic\n") as fd:
            config = transport.request_config(target, "document", fd)
            with patch.object(transport.subprocess, "Popen") as popen:
                process = popen.return_value
                process.communicate.return_value = (response(accepted()), b"PRIVATE ERROR")
                process.returncode = 0
                process.poll.return_value = 0
                result = transport.invoke(config, fd, 100, kind="document")
                self.assertEqual(result["state"], "sent")
                self.assertEqual(popen.call_args.args[0], ["/usr/bin/curl", "--disable", "--config", "-"])
                self.assertEqual(popen.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
                self.assertEqual(process.communicate.call_args.args, (config,))
                self.assertNotIn("SECRET_SENTINEL", repr(popen.call_args))
                self.assertNotIn("PRIVATE ERROR", repr(result))
                self.assertIn(b"retry = 0", config)
                self.assertIn(b"max-redirs = 0", config)
                self.assertIn(b"proxy = \"\"", config)

    def test_timeout_cleans_up_exact_child_and_never_retries(self):
        with patch.object(transport.subprocess, "Popen") as popen, \
                patch.object(transport.os, "killpg") as killpg:
            process = popen.return_value
            process.pid = 987654
            process.poll.return_value = None
            process.communicate.side_effect = [subprocess.TimeoutExpired("curl", 35), (b"", b"")]
            self.assertEqual(transport.invoke(b"synthetic", 3, 100), {"state": "unknown"})
            popen.assert_called_once()
            killpg.assert_called_once_with(987654, transport.signal.SIGTERM)

    def test_unstartable_curl_is_not_sent(self):
        with patch.object(transport.subprocess, "Popen", side_effect=FileNotFoundError):
            self.assertEqual(transport.invoke(b"synthetic", 3, 100), {"state": "not_sent"})

    def test_cleanup_race_does_not_turn_unknown_into_nothing_sent(self):
        with patch.object(transport.subprocess, "Popen") as popen, \
                patch.object(transport.os, "killpg", side_effect=ProcessLookupError):
            process = popen.return_value
            process.poll.return_value = None
            process.communicate.side_effect = [subprocess.TimeoutExpired("curl", 35), (b"", b"")]
            self.assertEqual(transport.invoke(b"synthetic", 3, 100), {"state": "unknown"})
            popen.assert_called_once()

    def test_watchdog_escalates_only_the_same_child(self):
        with patch.object(transport.subprocess, "Popen") as popen, \
                patch.object(transport.os, "killpg") as killpg:
            process = popen.return_value
            process.pid = 987654
            process.poll.return_value = None
            process.communicate.side_effect = [subprocess.TimeoutExpired("curl", 35),
                                               subprocess.TimeoutExpired("curl", 2), (b"", b"")]
            self.assertEqual(transport.invoke(b"synthetic", 3, 100), {"state": "unknown"})
            self.assertEqual([call.args for call in killpg.call_args_list],
                             [(987654, transport.signal.SIGTERM), (987654, transport.signal.SIGKILL)])
            popen.assert_called_once()


class LoopbackTest(unittest.TestCase):
    """Uses an ephemeral local CA, private fake config and 127.0.0.1 only."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cert, key = cls.root / "cert.pem", cls.root / "key.pem"
        subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=IP:127.0.0.1"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.cert = cert
        cls.requests = []
        cls.mode = "accepted"

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Includes a fake token in the URL; do not log it either.

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                cls.requests.append((self.path, self.headers["Content-Type"], body))
                if cls.mode in {"disconnect", "timeout"}:
                    if cls.mode == "timeout":
                        threading.Event().wait(0.15)
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                status = 429 if cls.mode == "rejected" else 200
                data = ({"ok": False, "error_code": 429, "description": "synthetic rejection"}
                        if status == 429 else accepted(-100 if cls.mode == "wrong_chat" else 100))
                if cls.mode == "malformed":
                    payload = b"incomplete response"
                else:
                    payload = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.addClassCleanup(cls.server.server_close)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        cls.server.socket = tls.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        private = cls.root / "private"
        private.mkdir(mode=0o700)
        cls.config = private / "target.conf"
        write_config(cls.config, "1234:LOOPBACK_FAKE", "100")
        cls.document = cls.root / "测试日报.md"
        cls.content = "# 合成日报\n\n正文 **bold** 🤖\n".encode()
        cls.document.write_bytes(cls.content)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def setUp(self):
        type(self).requests.clear()
        type(self).mode = "accepted"
        url = f"https://127.0.0.1:{self.server.server_port}"
        patcher = patch.object(transport, "API", url)
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, config, fd, chat, kind="document"):
        self.assertIn(f"https://127.0.0.1:{self.server.server_port}/".encode(), config)
        fixture_options = f'cacert = "{self.cert}"\n'.encode()
        if type(self).mode == "timeout":
            fixture_options += b"max-time = 0.05\n"
        return transport.invoke(config + fixture_options, fd, chat, kind=kind)

    def test_actual_curl_multipart_bytes_filename_caption_and_single_request(self):
        caption = '摘要\n第二行 "quoted" \\ @file;type=test 🤖'
        result = send_document(self.config, self.document, caption, self.runner)
        self.assertEqual(result["state"], "sent")
        self.assertEqual(len(self.requests), 1)
        path, content_type, body = self.requests[0]
        self.assertTrue(path.endswith("/sendDocument"))
        envelope = ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        parts = list(BytesParser(policy=default).parsebytes(envelope + body).iter_parts())
        fields = {part.get_param("name", header="content-disposition"): part for part in parts}
        self.assertEqual(set(fields), {"chat_id", "document", "caption", "disable_content_type_detection"})
        self.assertEqual(fields["document"].get_payload(decode=True), self.content)
        self.assertEqual(fields["document"].get_filename(), self.document.name)
        self.assertEqual(fields["document"].get_content_type(), "text/markdown")
        self.assertEqual(fields["caption"].get_payload(decode=True).decode(), caption)
        self.assertEqual(fields["chat_id"].get_payload(decode=True), b"100")

    def test_actual_curl_legacy_json_text(self):
        def runner(config, fd, chat):
            return self.runner(config, fd, chat, kind="text")
        self.assertEqual(send_message(self.config, "详细文字 🤖", runner)["state"], "sent")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(self.requests[0][2])["text"], "详细文字 🤖")
        self.assertTrue(self.requests[0][0].endswith("/sendMessage"))

    def test_server_rejection_disconnect_and_malformed_are_not_retried(self):
        for mode, expected in [("rejected", "rejected"), ("disconnect", "unknown"), ("timeout", "unknown"),
                               ("malformed", "unknown"), ("wrong_chat", "unknown")]:
            with self.subTest(mode=mode):
                type(self).mode = mode
                self.requests.clear()
                self.assertEqual(send_document(self.config, self.document, "summary", self.runner)["state"],
                                 expected)
                self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
