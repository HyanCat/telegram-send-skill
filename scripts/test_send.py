import json
import os
from pathlib import Path
import tempfile
import unittest

from secure_config import write_config
from telegram_send import send_message


class SendTest(unittest.TestCase):
    def test_one_message_uses_configured_chat_and_no_token_in_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            private = Path(root) / "private"
            private.mkdir(mode=0o700)
            config = private / "config"
            write_config(config, "1234:FAKE_TOKEN", "100")
            seen = []
            def runner(curl_config, fd, expected_chat):
                seen.append((json.loads(os.pread(fd, os.fstat(fd).st_size, 0)), expected_chat))
                return {"state": "sent", "message_id": 42}
            result = send_message(config, "测试文本", runner)
            self.assertEqual(result["state"], "sent")
            self.assertEqual(seen, [({"chat_id": 100, "text": "测试文本", "link_preview_options": {"is_disabled": True}}, 100)])

    def test_rejects_oversize_before_network(self):
        with self.assertRaises(ValueError):
            send_message(Path("/absent"), "x" * 3501, lambda *args: self.fail("unexpected request"))


if __name__ == "__main__":
    unittest.main()
