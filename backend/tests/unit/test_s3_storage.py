"""Unit tests for the private S3 storage adapter."""

from __future__ import annotations

from typing import Any

import pytest

from app.integrations.s3 import S3Storage


class _RecordingClient:
    """Captures the params a presign call was built with."""

    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    def generate_presigned_url(
        self, operation: str, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        """Record the presign parameters and return a stub URL."""
        self.params = Params
        return "https://signed.example/object"


@pytest.mark.parametrize(
    ("download_name", "expected"),
    [
        ("Quarterly Report.pdf", "Quarterly Report.pdf"),
        # A quote would close the header's quoted-string early, and CR/LF would
        # start a header of the attacker's choosing. Artifact names come
        # straight from a contributor's filename, so neither can reach S3.
        ('eviI".pdf', "eviI.pdf"),
        ("bad\r\nX-Injected: 1.pdf", "badX-Injected: 1.pdf"),
        ("../../etc/passwd", "passwd"),
        # Nothing usable left over must not produce `filename=""`.
        ('"\r\n', "download"),
    ],
)
def test_presigned_get_sanitises_the_download_filename(
    download_name: str, expected: str
) -> None:
    """A user-supplied filename cannot break out of the Content-Disposition."""
    storage = S3Storage.__new__(S3Storage)
    client = _RecordingClient()
    storage._client = client  # type: ignore[attr-defined]

    storage.presigned_get("bucket", "key", 900, download_name=download_name)

    assert (
        client.params["ResponseContentDisposition"]
        == f'attachment; filename="{expected}"'
    )


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
