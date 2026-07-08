"""Unit tests for the private S3 storage adapter."""

from __future__ import annotations

from app.integrations.s3 import S3Storage


def test_delete_prefix_deletes_listed_objects() -> None:
    """delete_prefix removes every object returned under a prefix."""
    deleted: list[str] = []

    class _Client:
        def get_paginator(self, operation_name: str) -> object:
            """Return a stub paginator for list_objects_v2."""

            class _Paginator:
                def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, object]]:
                    """Yield one page with two objects under the prefix."""
                    assert operation_name == "list_objects_v2"
                    return [
                        {
                            "Contents": [
                                {"Key": f"{Prefix}a.png"},
                                {"Key": f"{Prefix}b.png"},
                            ]
                        }
                    ]

            return _Paginator()

        def delete_object(self, Bucket: str, Key: str) -> None:
            """Record each deleted key."""
            deleted.append(Key)

    storage = S3Storage.__new__(S3Storage)
    storage._client = _Client()  # type: ignore[attr-defined]

    storage.delete_prefix("bucket", "frameworks/fw/artifacts/art/source-preview/")

    assert deleted == [
        "frameworks/fw/artifacts/art/source-preview/a.png",
        "frameworks/fw/artifacts/art/source-preview/b.png",
    ]
