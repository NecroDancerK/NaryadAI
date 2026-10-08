import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("visa_sample", Path(__file__).with_name("visa_sample.py"))
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


class RangeTest(unittest.TestCase):
    def test_server_ignoring_range_is_rejected(self):
        response = io.BytesIO(b"not-a-full-archive")
        response.status = 200
        response.headers = {}
        with patch.object(sample.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "refusing full archive"):
                sample.RemoteTar().read(512)

    def test_buffer_is_reused_and_seek_is_supported(self):
        response = io.BytesIO(b"abcdef")
        response.status = 206
        response.headers = {"Content-Range": "bytes 0-5/6"}
        with patch.object(sample.urllib.request, "urlopen", return_value=response) as request:
            remote = sample.RemoteTar()
            self.assertEqual(remote.read(2), b"ab")
            remote.seek(1)
            self.assertEqual(remote.read(3), b"bcd")
            self.assertEqual(remote.downloaded, 6)
            request.assert_called_once()

    def test_unbounded_read_is_forbidden(self):
        with self.assertRaises(ValueError):
            sample.RemoteTar().read()


if __name__ == "__main__":
    unittest.main()
