from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path


MAX_ARTIFACT_BYTES = 536870912


class AgentArtifactRejected(ValueError):
    pass


@dataclass(frozen=True)
class StoredAgentArtifact:
    storage_key: str
    sha256: str
    size_bytes: int
    created: bool


def _private_directory(root: Path, name: str) -> Path:
    directory = root / name
    directory.mkdir(mode=0o750, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise OSError("artifact storage contains an unsafe directory")
    if directory.resolve(strict=True).parent != root:
        raise OSError("artifact storage directory escapes its root")
    return directory


def _verified_existing(path: Path, expected_sha256: str, expected_size: int) -> bool:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    if not path.is_file() or path.is_symlink() or stat.st_size != expected_size:
        raise OSError("artifact storage contains an invalid object")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise OSError("artifact storage contains a corrupt object")
    return True


async def store_verified_agent_artifact(
    *,
    chunks: AsyncIterable[bytes],
    root_directory: str,
    expected_sha256: str,
    expected_size_bytes: int,
) -> StoredAgentArtifact:
    if expected_size_bytes < 1 or expected_size_bytes > MAX_ARTIFACT_BYTES:
        raise AgentArtifactRejected("catalog artifact size is outside the allowed range")

    root = Path(root_directory)
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise OSError("artifact storage root is not a directory")

    staging = _private_directory(root, ".staging")
    storage_key = f"{expected_sha256[:2]}/{expected_sha256}"
    destination_directory = _private_directory(root, expected_sha256[:2])
    destination = destination_directory / expected_sha256

    descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=staging)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    received = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.chmod(temporary, 0o600)
            async for chunk in chunks:
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected_size_bytes or received > MAX_ARTIFACT_BYTES:
                    raise AgentArtifactRejected("artifact is larger than catalog metadata")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

        if received != expected_size_bytes:
            raise AgentArtifactRejected(
                f"artifact size mismatch: expected {expected_size_bytes}, received {received}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise AgentArtifactRejected("artifact SHA-256 does not match catalog metadata")

        os.chmod(temporary, 0o440)
        if _verified_existing(destination, expected_sha256, expected_size_bytes):
            temporary.unlink()
            created = False
        else:
            os.replace(temporary, destination)
            directory_descriptor = os.open(destination_directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            created = True
        return StoredAgentArtifact(
            storage_key=storage_key,
            sha256=actual_sha256,
            size_bytes=received,
            created=created,
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
