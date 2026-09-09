"""Profile image URL resolution.

Avatars, banners and organization logos were built against a public-read bucket
and stored the deterministic URL the object would serve at. The buckets are not
public — every one of them sets ``RestrictPublicBuckets`` — so those URLs
returned 403 and no profile image ever rendered.

Rather than open a bucket, images are served the way artifacts already are: the
object key is stored, and a short-lived signed URL is minted when a profile is
serialized. That keeps the platform-wide "S3 is private" invariant intact.

The TTL is an hour rather than the 15 minutes artifacts use. An avatar is
re-fetched on every page that shows it, so a short expiry would break images on
a tab left open; an hour is long enough for a browsing session and still short
enough that a leaked URL is worth little.
"""

from __future__ import annotations

from typing import Protocol, overload
from urllib.parse import unquote, urlsplit

from app.core.config import get_settings
from app.integrations import s3

PROFILE_IMAGE_URL_TTL_SECONDS = 3600

# Every profile image key begins with one of these namespaces. They are what a
# legacy URL is anchored on when recovering its key.
PROFILE_IMAGE_PREFIXES = frozenset({"avatars", "banners", "org-logos"})


class _PresignsGets(Protocol):
    """The one storage capability this module needs."""

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a short-lived GET URL for a private object."""
        ...


def profile_image_key(stored: str | None) -> str | None:
    """Recover our own object key from a stored profile image value.

    Accepts either a bare key (what is written now) or a full URL into our own
    bucket (what rows written before presigned reads hold). Legacy rows must
    keep working: the alternative is that every avatar uploaded before the
    change stays broken permanently.

    A URL pointing anywhere else is somebody else's — an OAuth provider's
    avatar, a CDN — and returns None so the caller passes it through untouched
    rather than signing a key that was never in our bucket.

    Args:
        stored: The persisted ``avatar_url`` / ``banner_url`` / ``logo_key``.

    Returns:
        The object key, or None when no image is set or it is not ours.
    """
    if not stored:
        return None
    if not stored.startswith("http://") and not stored.startswith("https://"):
        return stored

    parts = urlsplit(stored)
    if not _is_own_bucket_host(parts.netloc):
        return None

    path = unquote(parts.path).lstrip("/")
    if not path:
        return None
    # Virtual-host style ("bucket.s3.region.amazonaws.com/key") puts the key at
    # the root; path-style, which LocalStack uses, prefixes it with the bucket.
    # Anchoring on the key's own namespace handles both without having to know
    # which bucket name a historical row was written against.
    segments = path.split("/")
    for index, segment in enumerate(segments):
        if segment in PROFILE_IMAGE_PREFIXES:
            return "/".join(segments[index:])
    return None


def _is_own_bucket_host(host: str) -> bool:
    """Return whether a URL host is this deployment's object storage.

    Covers the three shapes a stored URL can have: the configured endpoint
    (LocalStack), AWS virtual-host style (``bucket.s3.region.amazonaws.com``),
    and AWS path-style (``s3.region.amazonaws.com/bucket/key``).
    """
    if not host:
        return False
    settings = get_settings()
    if (
        settings.aws_endpoint_url is not None
        and host == urlsplit(settings.aws_endpoint_url).netloc
    ):
        return True
    if host.startswith(f"{settings.s3_avatars_bucket}.s3."):
        return True
    return host.startswith("s3.") and host.endswith(".amazonaws.com")


@overload
def resolve_profile_image_url(
    stored: str,
    *,
    storage: _PresignsGets | None = ...,
    bucket: str | None = ...,
) -> str: ...


@overload
def resolve_profile_image_url(
    stored: None,
    *,
    storage: _PresignsGets | None = ...,
    bucket: str | None = ...,
) -> None: ...


@overload
def resolve_profile_image_url(
    stored: str | None,
    *,
    storage: _PresignsGets | None = ...,
    bucket: str | None = ...,
) -> str | None: ...


def resolve_profile_image_url(
    stored: str | None,
    *,
    storage: _PresignsGets | None = None,
    bucket: str | None = None,
) -> str | None:
    """Resolve a stored profile image to a signed URL a browser can load.

    Overloaded because ``None`` comes back only for a falsy ``stored``: callers
    that pass a key they just minted get a plain ``str`` and should not have to
    narrow a value that can never be None.

    Args:
        stored: The persisted key or legacy URL.
        storage: Storage adapter; defaults to the shared S3 client.
        bucket: Bucket holding the image; defaults to the avatars bucket, which
            also holds organization logos.

    Returns:
        A short-lived signed URL for an image in our own bucket, the value
        unchanged when it points somewhere else, or None when nothing is set.
    """
    if not stored:
        return None
    key = profile_image_key(stored)
    if key is None:
        # Not ours to sign — an OAuth provider avatar or a CDN URL. Hand it back
        # as it was stored so it still renders.
        return stored
    settings = get_settings()
    return (storage or s3.storage).presigned_get(
        bucket=bucket or settings.s3_avatars_bucket,
        key=key,
        expires_in=PROFILE_IMAGE_URL_TTL_SECONDS,
    )
