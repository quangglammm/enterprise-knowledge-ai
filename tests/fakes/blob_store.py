from enterprise_knowledge.domain.errors import BlobNotFoundError


class InMemoryBlobStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_deletes_with: Exception | None = None

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise BlobNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        if self.fail_deletes_with is not None:
            raise self.fail_deletes_with
        self.objects.pop(key, None)
