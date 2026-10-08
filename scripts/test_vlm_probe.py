import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("vlm_probe", Path(__file__).with_name("vlm_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTest(unittest.TestCase):
    def test_remote_server_is_rejected_before_file_access(self):
        with patch("sys.argv", ["probe", "missing.jpg", "--url", "https://example.com"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                probe.main()
        self.assertEqual(error.exception.code, 2)

    def test_third_image_is_rejected(self):
        with patch("sys.argv", ["probe", "a.jpg", "b.jpg", "c.jpg"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                probe.main()

    def test_local_request_and_human_review_requirement(self):
        # Mock bytes exercise request serialization, not actual image decoding.
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo.jpg"
            image.write_bytes(b"mock-image")
            answer = {"choices": [{"message": {"content": json.dumps({"observations": [], "limitations": [], "needs_human_review": False})}, "finish_reason": "stop"}]}
            output = io.StringIO()
            with patch("sys.argv", ["probe", str(image)]), patch.object(probe.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())) as mocked:
                with contextlib.redirect_stdout(output):
                    probe.main()
            request = mocked.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8081/v1/chat/completions")
            payload = json.loads(request.data)
            self.assertEqual(payload["messages"][1]["content"][2]["type"], "image_url")
            self.assertTrue(json.loads(output.getvalue())["report"]["needs_human_review"])

    def test_truncated_response_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo.jpg"
            image.write_bytes(b"mock-image")
            answer = {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
            with patch("sys.argv", ["probe", str(image)]), patch.object(probe.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())):
                with self.assertRaisesRegex(SystemExit, "finish_reason=length"):
                    probe.main()


if __name__ == "__main__":
    unittest.main()
