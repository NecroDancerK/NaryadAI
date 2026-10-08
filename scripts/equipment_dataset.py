"""Validate a manually labelled local photo pilot; never calls a model or changes orders."""
import argparse
import hashlib
import json
from pathlib import Path

LABELS = {"visible_trace", "no_visible_trace", "unassessable"}
TARGET = "visible_liquid_trace"


def validate(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("target") != TARGET:
        raise ValueError("Expected version=1 and target=visible_liquid_trace")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("No labelled photos yet: samples must be a non-empty list")
    root = manifest_path.parent
    seen_hashes = set()
    equipment_splits = {}
    session_splits = {}
    counts = {split: {label: 0 for label in LABELS} for split in ("development", "evaluation")}
    warnings = []
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            raise ValueError(f"Sample {index}: expected object")
        for field in ("file", "sha256", "equipment_id", "capture_session", "reviewer",
                      "label", "split", "visible_evidence", "source", "usage_permission"):
            if not isinstance(sample.get(field), str) or not sample[field].strip():
                raise ValueError(f"Sample {index}: missing {field}")
        label, split = sample["label"], sample["split"]
        if label not in LABELS or split not in counts:
            raise ValueError(f"Sample {index}: invalid label or split")
        relative = Path(sample["file"])
        if relative.is_absolute():
            raise ValueError(f"Sample {index}: file must be relative to manifest")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Sample {index}: file escapes dataset directory")
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError(f"Sample {index}: unsupported image extension")
        if not path.is_file() or not 0 < path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError(f"Sample {index}: missing/empty image or image exceeds 10 MiB")
        content = path.read_bytes()
        # A signature check is not full image decoding or an assessment of photo quality.
        signatures = {".jpg": content.startswith(b"\xff\xd8\xff"),
                      ".jpeg": content.startswith(b"\xff\xd8\xff"),
                      ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                      ".webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP"}
        if not signatures[path.suffix.lower()]:
            raise ValueError(f"Sample {index}: image signature does not match extension")
        digest = hashlib.sha256(content).hexdigest()
        if sample["sha256"] != digest:
            raise ValueError(f"Sample {index}: SHA-256 mismatch; actual={digest}")
        if digest in seen_hashes:
            raise ValueError(f"Sample {index}: duplicate photo")
        seen_hashes.add(digest)
        for field, groups in (("equipment_id", equipment_splits), ("capture_session", session_splits)):
            identifier = sample[field].strip()
            if identifier in groups and groups[identifier] != split:
                raise ValueError(f"Sample {index}: {field} appears in both splits")
            groups[identifier] = split
        counts[split][label] += 1
    for split, labels in counts.items():
        if not labels["visible_trace"] or not labels["no_visible_trace"]:
            warnings.append(f"{split}: both assessable classes are needed before comparing models")
    return {"photos": len(samples), "counts": counts, "warnings": warnings,
            "needs_human_review": True,
            "scope": "Metadata/hash checks only, not label accuracy, near-duplicate detection or full image decoding"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        report = validate(args.manifest)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
