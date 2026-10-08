"""Read only selected VisA files from the official uncompressed S3 tar via HTTP ranges."""
import hashlib
import argparse
import io
import json
import tarfile
import urllib.request
from pathlib import Path

SOURCE = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
DESTINATION = Path(".local-models/datasets/visa-sample")


class RemoteTar(io.RawIOBase):
    def __init__(self):
        self.position = 0
        self.start = -1
        self.buffer = b""
        self.downloaded = 0

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence == 0:
            self.position = offset
        elif whence == 1:
            self.position += offset
        else:
            raise ValueError("end-relative seek unsupported")
        return self.position

    def read(self, size=-1):
        if size < 0:
            raise ValueError("unbounded read forbidden")
        if size == 0:
            return b""
        if not self.start <= self.position or self.position + size > self.start + len(self.buffer):
            end = self.position + max(size, 65536) - 1
            request = urllib.request.Request(SOURCE, headers={"Range": f"bytes={self.position}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {self.position}-"):
                    raise RuntimeError("Server did not honor range; refusing full archive download")
                self.buffer = response.read(end - self.position + 1)
            self.start = self.position
            self.downloaded += len(self.buffer)
        offset = self.position - self.start
        result = self.buffer[offset:offset + size]
        self.position += len(result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-per-label", type=int, default=0)
    parser.add_argument("--per-label", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    if args.skip_per_label < 0 or not 1 <= args.per_label <= 10:
        parser.error("Invalid selection size")
    destination = args.output
    if destination.exists() and any(destination.iterdir()):
        parser.error("Output directory must be new or empty")
    destination.mkdir(parents=True, exist_ok=True)
    samples = []
    counts = {"normal": 0, "anomaly": 0}
    seen = {"normal": 0, "anomaly": 0}
    remote = RemoteTar()
    with tarfile.open(fileobj=remote, mode="r:") as archive:
        for index, member in enumerate(archive):
            if index % 25 == 0:
                print(f"Scanned {index} headers; downloaded {remote.downloaded / 1048576:.1f} MiB", flush=True)
            # First category in the official archive; fixed selection, not model-dependent.
            if not member.isfile() or not member.name.startswith("candle/Data/Images/"):
                continue
            label = "anomaly" if "/Anomaly/" in member.name else "normal" if "/Normal/" in member.name else None
            if label is None:
                continue
            seen[label] += 1
            if seen[label] <= args.skip_per_label or counts[label] >= args.per_label:
                continue
            if member.size > 10 * 1048576:
                raise ValueError("oversized sample")
            data = archive.extractfile(member).read()
            filename = f"sample-{len(samples) + 1:02d}{Path(member.name).suffix}"
            # Never extract tar paths: flat, locally generated filenames only.
            (destination / filename).write_bytes(data)
            samples.append({"file": filename, "label": label, "category": "candle",
                            "source_member": member.name, "sha256": hashlib.sha256(data).hexdigest()})
            counts[label] += 1
            print(f"Selected {filename}: {label}", flush=True)
            if all(value == args.per_label for value in counts.values()):
                break
    if len(samples) != 2 * args.per_label:
        raise RuntimeError(f"Incomplete selection: {counts}")
    (destination / "manifest.json").write_text(json.dumps({"source": SOURCE,
        "license": "CC BY 4.0", "authors": "Yang Zou, Jongheon Jeong, Latha Pemula, Dongqing Zhang, Onkar Dabeer",
        "selection": f"Skip first {args.skip_per_label} per label, take next {args.per_label}, official tar order, candle; exploratory only",
        "downloaded_bytes": remote.downloaded, "samples": samples}, indent=2), encoding="utf-8")
    print(f"Done: {len(samples)} images, {remote.downloaded / 1048576:.1f} MiB transferred", flush=True)


if __name__ == "__main__":
    main()
