"""Filesystem BlobStore for local development. S3 replaces it in AWS (Week 8)."""

import asyncio
import os
import re
from pathlib import Path

from enterprise_knowledge.domain.errors import BlobNotFoundError

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(self._write, self._path(key), data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise BlobNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    def _path(self, key: str) -> Path:
        if not _SAFE_KEY.match(key) or any(part in {".", ".."} for part in key.split("/")):
            raise ValueError(f"unsafe blob key: {key!r}")
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError(f"blob key escapes the store root: {key!r}")
        return path

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)  # atomic: readers never see a partial file
