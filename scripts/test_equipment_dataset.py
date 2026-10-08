import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("equipment_dataset", Path(__file__).with_name("equipment_dataset.py"))
dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dataset)


class DatasetTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "manifest.json"
        # Synthetic PNG signature exercises file checks, not an actual image decoder.
        content = b"\x89PNG\r\n\x1a\nsynthetic-fixture"
        (self.root / "photo.png").write_bytes(content)
        self.sample = {"file": "photo.png", "sha256": hashlib.sha256(content).hexdigest(),
                       "equipment_id": "pump-1", "capture_session": "session-1", "reviewer": "reviewer-1",
                       "label": "visible_trace", "split": "evaluation", "visible_evidence": "trace on left housing",
                       "source": "own photo", "usage_permission": "owner permits local evaluation"}

    def check(self, samples):
        self.path.write_text(json.dumps({"version": 1, "target": dataset.TARGET, "samples": samples}))
        return dataset.validate(self.path)

    def second(self):
        content = b"\x89PNG\r\n\x1a\nsecond-fixture"
        (self.root / "second.png").write_bytes(content)
        return dict(self.sample, file="second.png", sha256=hashlib.sha256(content).hexdigest())

    def test_valid_metadata_does_not_claim_complete_dataset(self):
        result = self.check([self.sample])
        self.assertEqual(result["photos"], 1)
        self.assertTrue(result["needs_human_review"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_empty_template_is_not_evaluation_ready(self):
        with self.assertRaisesRegex(ValueError, "No labelled photos"):
            self.check([])

    def test_missing_review_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing reviewer"):
            self.check([dict(self.sample, reviewer="")])

    def test_hash_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.check([dict(self.sample, sha256="wrong")])

    def test_duplicate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate photo"):
            self.check([self.sample, self.sample])

    def test_equipment_cannot_cross_splits(self):
        with self.assertRaisesRegex(ValueError, "equipment_id appears in both"):
            self.check([self.sample, dict(self.second(), split="development", capture_session="other")])

    def test_session_cannot_cross_splits(self):
        with self.assertRaisesRegex(ValueError, "capture_session appears in both"):
            self.check([self.sample, dict(self.second(), split="development", equipment_id="other")])

    def test_directory_escape_is_rejected_before_reading(self):
        with self.assertRaisesRegex(ValueError, "escapes dataset"):
            self.check([dict(self.sample, file="../outside.png")])

    def test_invalid_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid label"):
            self.check([dict(self.sample, label="repair_successful")])

    def test_non_image_is_rejected(self):
        (self.root / "photo.png").write_bytes(b"not a PNG")
        with self.assertRaisesRegex(ValueError, "signature"):
            self.check([self.sample])


if __name__ == "__main__":
    unittest.main()
