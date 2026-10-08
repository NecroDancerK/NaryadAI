import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("visa_benchmark", Path(__file__).with_name("visa_benchmark.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class SummaryTest(unittest.TestCase):
    def test_errors_and_abstentions_are_not_counted_as_correct(self):
        rows = [
            {"label": label, "elapsed_seconds": 2, "report": {"decision": decision}}
            for label, decision in [("anomaly", "defect"), ("anomaly", "no_visible_defect"),
                                    ("normal", "defect"), ("normal", "no_visible_defect"),
                                    ("anomaly", "uncertain")]
        ] + [{"label": "normal", "error": "timeout"}]
        summary = benchmark.summarize(rows)
        self.assertEqual(summary, {"total": 6, "valid": 5, "errors": 1, "detected_anomalies": 1,
            "missed_anomalies": 1, "false_alarms": 1, "correct_normal": 1, "uncertain": 1, "median_seconds": 2})

    def test_empty_run_is_not_success(self):
        self.assertEqual(benchmark.summarize([])["valid"], 0)
        self.assertIsNone(benchmark.summarize([])["median_seconds"])

    def test_liquid_labels_use_same_confusion_counts(self):
        rows = [{"label": label, "elapsed_seconds": 1, "report": {"decision": decision}}
                for label, decision in [("visible_trace", "defect"), ("visible_trace", "no_visible_defect"),
                                        ("no_visible_trace", "defect"), ("no_visible_trace", "no_visible_defect")]]
        summary = benchmark.summarize(rows)
        for key in ("detected_anomalies", "missed_anomalies", "false_alarms", "correct_normal"):
            self.assertEqual(summary[key], 1)

    def test_liquid_prompt_never_contains_source_filename_or_label(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "visible_trace-source.jpg"
            image.write_bytes(b"mock image")
            answer = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
                {"decision": "uncertain", "observations": [], "limitations": []})}}]}
            with patch.object(benchmark.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())) as mocked:
                report = benchmark.evaluate(image, scenario="liquid-trace")
            payload = json.loads(mocked.call_args.args[0].data)
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn(image.name, serialized)
            self.assertNotIn("visible_trace", serialized)
            self.assertEqual(payload["messages"][1]["content"][0]["text"], benchmark.LIQUID_PROMPT)
            self.assertEqual(len(report["prompt_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
