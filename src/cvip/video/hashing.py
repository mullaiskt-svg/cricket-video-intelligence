"""Sampled content hash for Video Loader (FR-014).

See research.md "Compute file_hash from a sampled digest, not the full file":
SHA-256 over the first 1 MiB, the last 1 MiB, and the exact file size -- not a
full-file read. This identifies "very likely the same file", not
cryptographic integrity, and stays within the SC-001 time budget regardless
of file size.
"""

from __future__ import annotations

import hashlib
import os

SAMPLE_SIZE_BYTES = 1024 * 1024  # 1 MiB, per research.md


def compute_file_hash(file_path: str) -> str:
    """Return a stable, sampled digest identifying `file_path`'s content."""
    file_size = os.path.getsize(file_path)
    digest = hashlib.sha256()

    with open(file_path, "rb") as f:
        prefix = f.read(SAMPLE_SIZE_BYTES)
        digest.update(prefix)

        suffix_start = max(file_size - SAMPLE_SIZE_BYTES, len(prefix))
        f.seek(suffix_start)
        suffix = f.read(SAMPLE_SIZE_BYTES)
        digest.update(suffix)

    digest.update(str(file_size).encode("utf-8"))
    return digest.hexdigest()
