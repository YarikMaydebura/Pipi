"""Download a model file once into a gitignored cache folder and verify its SHA-256."""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

CHUNK_BYTES = 1 << 16
MAX_MODEL_BYTES = 50 * 1024 * 1024  # Silero is ~2.3 MB; refuse anything absurd


class ModelDownloadError(Exception):
    """The model could not be downloaded or its checksum did not match."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(path: Path, *, url: str, sha256: str, timeout_s: float) -> Path:
    """Return ``path``; download it first if it is missing or its checksum is wrong."""
    if path.is_file() and sha256_of(path) == sha256:
        return path
    if not url.startswith("https://"):
        raise ModelDownloadError(f"refusing non-https model URL: {url}")
    partial = path.with_suffix(path.suffix + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _download(url, partial, timeout_s)
        actual = sha256_of(partial)
        if actual != sha256:
            raise ModelDownloadError(f"checksum mismatch for {url}: got {actual[:12]}...")
        os.replace(partial, path)
    except ModelDownloadError:
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:  # includes urllib errors and socket timeouts
        partial.unlink(missing_ok=True)
        raise ModelDownloadError(f"could not download {url}: {exc}") from exc
    return path


def _download(url: str, target: Path, timeout_s: float) -> None:
    received = 0
    with urllib.request.urlopen(url, timeout=timeout_s) as response, target.open("wb") as out:
        for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
            received += len(chunk)
            if received > MAX_MODEL_BYTES:
                raise ModelDownloadError(f"model at {url} is larger than {MAX_MODEL_BYTES} bytes")
            out.write(chunk)
