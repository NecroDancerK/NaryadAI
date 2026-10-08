"""Download eight fixed original synthetic Oil leak images, not the whole archive."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode, urlparse

BASE = "https://data.mendeley.com"
DATASET = "nbxzxn3ffk"
SOURCE = f"{BASE}/datasets/{DATASET}/1"
AUTHORS = "Matteo Cardoni, Danilo Pau, Laura Falaschetti, Claudio Turchetti, Marco Lattuada"
# Fixed before model responses. Balanced steel/white and camera positions 2/10.
SELECTION = ((1, 1, 2), (1, 4, 10), (4, 1, 10), (4, 4, 2),
             (21, 1, 2), (22, 1, 2), (21, 1, 10), (22, 1, 10))
LIMIT = 10 * 1024 * 1024


def get_json(url):
    content = fetch(url)
    if len(content) > LIMIT:
        raise ValueError("Metadata exceeds limit")
    return json.loads(content)


def fetch(url, limit=LIMIT):
    # Mendeley's public endpoint rejects this host's urllib client; curl works.
    result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
        "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "3",
        "--max-time", "60", "--max-filesize", str(limit), url],
        capture_output=True, check=True, timeout=65)
    if len(result.stdout) > limit:
        raise ValueError("Response exceeds size limit")
    return result.stdout


def folder_paths(folders):
    by_id = {item["id"]: item for item in folders}
    def path(identifier, visited=None):
        visited = set() if visited is None else visited
        if identifier in visited:
            raise ValueError("Folder cycle")
        visited.add(identifier)
        folder = by_id[identifier]
        return (path(folder["parent_id"], visited) + "/" if folder.get("parent_id") else "") + folder["name"]
    return {path(identifier): identifier for identifier in by_id}


def download(details):
    url = details["download_url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.mendeley.com":
        raise ValueError("Unexpected download origin")
    size = details["size"]
    if not isinstance(size, int) or not 0 < size <= LIMIT:
        raise ValueError("Invalid/oversized image")
    content = fetch(url, size)
    if len(content) != size or hashlib.sha256(content).hexdigest() != details["sha256_hash"]:
        raise ValueError("Image size or published SHA-256 mismatch")
    if not content.startswith(b"\xff\xd8\xff"):
        raise ValueError("Not a JPEG")
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local-models/datasets/oil-leak-sample"))
    args = parser.parse_args()
    destination = args.output
    if destination.exists() and any(destination.iterdir()):
        parser.error("Output must be new or empty")
    paths = folder_paths(get_json(f"{BASE}/public-api/datasets/{DATASET}/folders/1"))
    selected = []
    cache = {}
    for group, variant, camera in SELECTION:
        folder = f"Oil_leak_dataset/Junction_images/Group_{group}/set_{variant}/natural_light"
        if folder not in cache:
            query = urlencode({"folder_id": paths[folder], "version": 1, "$start": 0, "$limit": 1000})
            cache[folder] = get_json(f"{BASE}/public-api/datasets/{DATASET}/files?{query}")
        name = f"g{group}s{variant}.{camera}nat.jpg"
        matches = [item for item in cache[folder] if item["filename"] == name]
        if len(matches) != 1:
            raise ValueError(f"Missing or ambiguous original: {folder}/{name}")
        selected.append((group, folder, matches[0]))
    destination.mkdir(parents=True, exist_ok=True)
    samples = []
    for index, (group, folder, item) in enumerate(selected, 1):
        content = download(item["content_details"])
        filename = f"sample-{index:02d}.jpg"
        (destination / filename).write_bytes(content)
        samples.append({"file": filename, "sha256": hashlib.sha256(content).hexdigest(),
            "label": "visible_trace" if group <= 20 else "no_visible_trace",
            "category": "synthetic_shaft_junction", "split": "evaluation",
            "equipment_id": "shared-synthetic-junction", "capture_session": f"synthetic-group-{group}",
            "reviewer": "dataset-author-label; not locally expert-reviewed",
            "visible_evidence": "Author-defined rendered leak presence/absence, not confirmed real-world diagnosis",
            "source": SOURCE, "source_member": f"{folder}/{item['filename']}", "source_file_id": item["id"],
            "usage_permission": "Published CC BY 4.0; attribution retained in manifest and report"})
        print(f"Downloaded {filename}: {len(content)} bytes", flush=True)
    manifest = {"version": 1, "target": "visible_liquid_trace", "synthetic": True,
        "source": SOURCE, "license": "CC BY 4.0", "authors": AUTHORS,
        "label_source": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8591346/ section 1",
        "selection": "Fixed 8 originals; groups 1/4 leaks, 21/22 no leak; cameras 2/10; no training or independent object split",
        "downloaded_image_bytes": sum((destination / item["file"]).stat().st_size for item in samples),
        "samples": samples}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done: {len(samples)} original synthetic images", flush=True)


if __name__ == "__main__":
    main()
