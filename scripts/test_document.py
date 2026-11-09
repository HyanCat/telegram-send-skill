"""Synthetic files and configuration only; never contact Telegram."""
import contextlib
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import curl_transport as transport
from secure_config import write_config
import telegram_send as cli


class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        private = self.root / "private"
        private.mkdir(mode=0o700)
        self.config = private / "target.conf"
        write_config(self.config, "1234:SYNTHETIC_TOKEN", "100")
        self.document = self.root / "日报 2026-11-09.md"
        self.content = "# 测试日报\n\n- 合成数据 🤖\n".encode()
        self.document.write_bytes(self.content)
        self.calls = []

    def runner(self, config, fd, chat):
        self.calls.append((config, os.pread(fd, os.fstat(fd).st_size, 0), chat))
        self.assertEqual(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & transport.REQUIRED_SEALS,
                         transport.REQUIRED_SEALS)
        return {"state": "sent", "message_id": 42}

    def test_document_and_multiline_caption_use_one_immutable_request(self):
        def mutate_source(config, fd, chat):
            self.document.write_text("changed after snapshot")
            with self.assertRaises(OSError):
                os.write(fd, b"cannot change snapshot")
            return self.runner(config, fd, chat)
        result = cli.send_document(self.config, self.document, "摘要\n详细内容见附件", mutate_source)
        self.assertEqual(result, {"state": "sent", "message_id": 42})
        self.assertEqual(len(self.calls), 1)
        config, content, chat = self.calls[0]
        self.assertEqual(content, self.content)
        self.assertEqual(chat, 100)
        self.assertIn(b"/sendDocument", config)
        self.assertNotIn(b"/sendMessage", config)
        self.assertIn("filename=日报 2026-11-09.md;type=text/markdown".encode(), config)
        self.assertIn(b"disable_content_type_detection=true", config)
        self.assertIn("caption=摘要\\n详细内容见附件".encode(), config)
        self.assertNotIn(str(self.root).encode(), config)

    def test_no_caption_and_explicit_filename(self):
        cli.send_document(self.config, self.document, runner=self.runner, filename="report.markdown")
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn(b"caption=", self.calls[0][0])
        self.assertIn(b"filename=report.markdown", self.calls[0][0])

    def test_caption_boundary_counts_utf16_units(self):
        cli.send_document(self.config, self.document, "🤖" * 512, self.runner)
        with self.assertRaises(ValueError):
            cli.send_document(self.config, self.document, "🤖" * 513, self.runner)
        self.assertEqual(len(self.calls), 1)

    def test_unsafe_filename_and_caption_do_not_send(self):
        names = ["../leak.md", "a/b.md", "a;type=text.md", 'a".md', "a\\.md",
                 "a\n.md", ".hidden.md", "a\u202e.md", " x.md", "a.txt", "", "界" * 43 + ".md"]
        for filename in names:
            with self.subTest(filename=repr(filename)), self.assertRaises(ValueError):
                cli.send_document(self.config, self.document, runner=self.runner, filename=filename)
        with self.assertRaises(ValueError):
            cli.send_document(self.config, self.document, "summary\0injection", self.runner)
        self.assertEqual(self.calls, [])

    def test_missing_directory_symlink_fifo_rejected(self):
        link = self.root / "link.md"
        link.symlink_to(self.document)
        fifo = self.root / "pipe.md"
        os.mkfifo(fifo)
        directory = self.root / "directory.md"
        directory.mkdir()
        for path in [self.root / "absent.md", directory, link, fifo]:
            with self.subTest(path=path.name), self.assertRaises((OSError, ValueError)):
                cli.send_document(self.config, path, runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_empty_non_utf8_and_nul_rejected(self):
        for content in [b"", b"\xff\xfe", b"text\0text"]:
            self.document.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                cli.send_document(self.config, self.document, runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_document_size_boundary_and_oversize(self):
        self.document.write_bytes(b"x" * transport.DOCUMENT_LIMIT)
        cli.send_document(self.config, self.document, runner=self.runner)
        self.assertEqual(len(self.calls[0][1]), transport.DOCUMENT_LIMIT)
        with self.document.open("ab") as output:
            output.write(b"x")
        with self.assertRaisesRegex(ValueError, "PART_TOO_LARGE"):
            cli.send_document(self.config, self.document, runner=self.runner)
        self.assertEqual(len(self.calls), 1)

    def test_unsealed_document_rejected(self):
        descriptor = os.memfd_create("unsealed-test")
        self.addCleanup(os.close, descriptor)
        os.write(descriptor, self.content)
        with self.assertRaisesRegex(ValueError, "SEALED_PART_REQUIRED"):
            transport.send_sealed({"token": "1234:FAKE", "chat_id": 100}, "document",
                                  descriptor, self.runner)
        self.assertEqual(self.calls, [])

    def run_cli(self, argv, stdin, result):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["telegram_send.py", "--config", str(self.config), *argv]), \
                patch.object(sys, "stdin", io.StringIO(stdin)), \
                patch.object(transport, "invoke", return_value=result) as invoke, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main()
        return status, stdout.getvalue(), stderr.getvalue(), invoke

    def test_cli_legacy_positional_and_stdin_text(self):
        for argv, stdin in [(["旧文字"], "ignored"), ([], "旧文字")]:
            status, stdout, stderr, invoke = self.run_cli(argv, stdin, {"state": "sent", "message_id": 42})
            self.assertEqual((status, stdout, stderr), (0, "Sent (message id: 42).\n", ""))
            invoke.assert_called_once()
            self.assertIn(b"/sendMessage", invoke.call_args.args[0])

    def test_cli_document_caption_via_stdin_and_empty(self):
        for stdin in ["概要\n见附件", ""]:
            status, stdout, stderr, invoke = self.run_cli(
                ["--document", str(self.document)], stdin, {"state": "sent", "message_id": 42})
            self.assertEqual((status, stdout, stderr), (0, "Sent document (message id: 42).\n", ""))
            invoke.assert_called_once()
            self.assertEqual(invoke.call_args.kwargs, {"kind": "document"})

    def test_cli_failures_never_report_sent_or_retry(self):
        for result, marker in [({"state": "unknown"}, "may already be delivered"),
                               ({"state": "rejected", "http_status": 429}, "HTTP 429"),
                               ({"state": "not_sent"}, "could not start")]:
            status, stdout, stderr, invoke = self.run_cli(["--document", str(self.document)], "", result)
            self.assertEqual(status, 1)
            self.assertEqual(stdout, "")
            self.assertIn(marker, stderr)
            self.assertNotIn("SYNTHETIC_TOKEN", stderr)
            invoke.assert_called_once()

    def test_cli_bad_document_and_oversize_text_are_local_errors(self):
        for argv, stdin in [(["--document", str(self.document)], "x" * 1025), ([], "x" * 3501)]:
            status, stdout, stderr, invoke = self.run_cli(argv, stdin, {"state": "sent", "message_id": 42})
            self.assertEqual((status, stdout), (2, ""))
            self.assertIn("Nothing sent", stderr)
            invoke.assert_not_called()

    def test_unknown_attempt_does_not_send_a_followup_or_fallback(self):
        def unknown(config, fd, chat):
            self.runner(config, fd, chat)
            return {"state": "unknown"}
        self.assertEqual(cli.send_document(self.config, self.document, "summary", unknown),
                         {"state": "unknown"})
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
