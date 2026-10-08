import hashlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("oil_leak_sample", Path(__file__).with_name("oil_leak_sample.py"))
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


class DownloadTest(unittest.TestCase):
    def details(self, content):
        return {"download_url": "https://data.mendeley.com/public-files/example", "size": len(content),
                "sha256_hash": hashlib.sha256(content).hexdigest()}

    def test_verified_jpeg(self):
        content = b"\xff\xd8\xffmock-image"
        with patch.object(sample, "fetch", return_value=content):
            self.assertEqual(sample.download(self.details(content)), content)

    def test_corrupt_download_is_rejected(self):
        content = b"\xff\xd8\xffmock-image"
        with patch.object(sample, "fetch", return_value=b"x" * len(content)):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                sample.download(self.details(content))

    def test_unexpected_origin_is_rejected_before_network(self):
        details = self.details(b"abc")
        details["download_url"] = "https://example.com/image.jpg"
        with patch.object(sample, "fetch") as mocked, self.assertRaisesRegex(ValueError, "origin"):
            sample.download(details)
        mocked.assert_not_called()

    def test_folder_cycle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            sample.folder_paths([{"id": "a", "parent_id": "b", "name": "a"},
                                 {"id": "b", "parent_id": "a", "name": "b"}])


if __name__ == "__main__":
    unittest.main()
