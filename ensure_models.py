#!/usr/bin/env python3
"""Download Kokoro weights when they are missing or still Git LFS pointers."""

from __future__ import annotations

import fcntl
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"
RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
)

# Names, sizes, and hashes match the model-files-v1.1 release used by kokoro-onnx 0.6.
FILES = {
    "kokoro-v1.0.int8.onnx": (
        f"{RELEASE}/kokoro-v1.0.int8.onnx",
        114_119_327,
        "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    ),
    "kokoro-v1.0.onnx": (
        f"{RELEASE}/kokoro-v1.0.onnx",
        325_505_369,
        "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    ),
    "voices-v1.0.bin": (
        f"{RELEASE}/voices-v1.0.bin",
        28_214_398,
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
}


def is_ready(path: Path, size: int) -> bool:
    if not path.is_file():
        return False
    try:
        actual = path.stat().st_size
    except OSError:
        return False
    # Git LFS pointers are about 130 bytes, so a size mismatch means the
    # real weights are not here yet.
    return actual == size


def _report(report, message: str) -> None:
    report(message)


def _download(path: Path, url: str, size: int, digest: str, report) -> None:
    partial = path.with_name(path.name + ".partial")
    _report(report, f"downloading {path.name} ({size / 1_000_000:.0f} MB)")
    request = urllib.request.Request(url, headers={"User-Agent": "ChickEN"})
    hasher = hashlib.sha256()
    got = 0
    next_mark = 10
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                got += len(chunk)
                if size and got * 100 // size >= next_mark:
                    _report(report, f"  {path.name} {min(next_mark, 100)}%")
                    next_mark += 10
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"could not download {path.name}: {exc}") from exc

    actual = hasher.hexdigest()
    if got != size or actual != digest:
        partial.unlink(missing_ok=True)
        raise SystemExit(
            f"{path.name} download failed: got {got} bytes, sha256 {actual}"
        )
    partial.replace(path)
    _report(report, f"{path.name} ready")


def ensure_models(names: list[str] | None = None, report=print) -> None:
    wanted = names if names else list(FILES)
    unknown = [name for name in wanted if name not in FILES]
    if unknown:
        raise SystemExit(f"unknown model file: {', '.join(unknown)}")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        url, size, digest = FILES[name]
        path = MODEL_DIR / name
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if is_ready(path, size):
                continue
            if path.is_file():
                _report(report, f"{name} is not a usable model file; replacing it")
            _download(path, url, size, digest, report)


def main() -> None:
    ensure_models(sys.argv[1:] or None)


if __name__ == "__main__":
    main()
