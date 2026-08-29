"""Shared response schema for private file downloads.

Private artifacts are never proxied through the API. Endpoints hand the caller
a short-lived presigned S3 URL as data, and the browser navigates to it. That
keeps the credential in the Authorization header where it belongs: an earlier
design redirected instead and accepted the access token as a `?token=` query
parameter, which put a full-privilege credential into browser history, Referer
headers, and proxy logs.
"""

from pydantic import BaseModel


class DownloadUrlResponse(BaseModel):
    """A short-lived presigned URL for one private object.

    Attributes:
        download_url: Presigned S3 URL the caller should navigate to. Expires
            on its own schedule, so it is a capability rather than a session
            credential and cannot be replayed against the wider API.
    """

    download_url: str
