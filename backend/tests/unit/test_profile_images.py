"""Unit tests for profile image URL resolution.

Avatars, banners and org logos live in a private bucket, so the URL a client
renders has to be presigned at serialization time rather than derived from the
key. These cases pin that, plus the tolerance for rows written before the
change that hold a full bucket URL instead of a key.
"""

from __future__ import annotations

import pytest

from app.core.profile_images import profile_image_key, resolve_profile_image_url


class _Storage:
    """Records presign calls and returns a recognisable URL."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a stub presigned URL and record the arguments."""
        self.calls.append((bucket, key, expires_in))
        return f"https://signed.example/{key}?sig=abc"


@pytest.mark.parametrize(
    ("stored", "expected_key"),
    [
        ("avatars/user-1/pic.png", "avatars/user-1/pic.png"),
        # Rows written before profile images moved to presigned reads hold the
        # full virtual-host URL. The key has to be recovered, or every avatar
        # uploaded before the change stays broken forever.
        (
            "https://auracles-avatars-dev.s3.eu-west-2.amazonaws.com/avatars/user-1/pic.png",
            "avatars/user-1/pic.png",
        ),
        # AWS path-style puts the bucket in the path; the key namespace is what
        # anchors the scan, so the bucket segment falls away.
        (
            "https://s3.eu-west-2.amazonaws.com/auracles-avatars-dev/banners/u/b.png",
            "banners/u/b.png",
        ),
        # LocalStack writes path-style URLs against the configured endpoint.
        (
            "http://localhost:4566/auracles-avatars-dev/avatars/user-1/pic.png",
            "avatars/user-1/pic.png",
        ),
    ],
)
def test_profile_image_key_recovers_the_object_key(
    stored: str, expected_key: str
) -> None:
    """The stored value resolves to an object key whether it is one or a URL."""
    assert profile_image_key(stored) == expected_key


def test_profile_image_key_passes_through_none() -> None:
    """An unset image stays unset rather than becoming a broken key."""
    assert profile_image_key(None) is None


def test_resolve_profile_image_url_presigns_the_key() -> None:
    """A stored key is served through a short-lived signed URL."""
    storage = _Storage()

    url = resolve_profile_image_url(
        "avatars/user-1/pic.png", storage=storage, bucket="avatars-bucket"
    )

    assert url == "https://signed.example/avatars/user-1/pic.png?sig=abc"
    assert storage.calls == [("avatars-bucket", "avatars/user-1/pic.png", 3600)]


def test_resolve_profile_image_url_presigns_a_legacy_url_row() -> None:
    """A legacy full-URL row is re-signed rather than returned as-is.

    Returning it unchanged is what produced the 403: the bucket blocks all
    public access, so the deterministic URL the column holds serves nothing.
    """
    storage = _Storage()

    url = resolve_profile_image_url(
        "https://auracles-avatars-dev.s3.eu-west-2.amazonaws.com/avatars/u/p.png",
        storage=storage,
        bucket="avatars-bucket",
    )

    assert url == "https://signed.example/avatars/u/p.png?sig=abc"


def test_resolve_profile_image_url_leaves_a_foreign_url_alone() -> None:
    """A URL into somebody else's storage is passed through untouched.

    An OAuth provider avatar or a CDN URL was never in our bucket, so signing a
    key derived from its path would produce a link to nothing.
    """
    storage = _Storage()

    url = resolve_profile_image_url(
        "https://lh3.googleusercontent.com/a/avatars/abc123",
        storage=storage,
        bucket="avatars-bucket",
    )

    assert url == "https://lh3.googleusercontent.com/a/avatars/abc123"
    assert storage.calls == []


def test_resolve_profile_image_url_returns_none_when_unset() -> None:
    """No image means no URL, and no pointless presign call."""
    storage = _Storage()

    assert (
        resolve_profile_image_url(None, storage=storage, bucket="avatars-bucket")
        is None
    )
    assert storage.calls == []
