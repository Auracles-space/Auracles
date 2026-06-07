"""S3 adapter for private Auracles object storage."""

from __future__ import annotations

from typing import Any, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import get_settings


class S3Storage:
    """Small wrapper around S3 operations used by request services."""

    def __init__(self) -> None:
        """Create an S3 client from application settings."""
        settings = get_settings()
        import boto3  # type: ignore[import-untyped]

        kwargs: dict[str, Any] = {"region_name": settings.aws_default_region}
        if settings.aws_access_key_id is not None:
            kwargs["aws_access_key_id"] = (
                settings.aws_access_key_id.get_secret_value()
            )
        if settings.aws_secret_access_key is not None:
            kwargs["aws_secret_access_key"] = (
                settings.aws_secret_access_key.get_secret_value()
            )
        if settings.aws_endpoint_url is not None:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        self._client = boto3.client("s3", **kwargs)

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Create a presigned POST policy with S3-enforced upload constraints."""
        return cast(
            dict[str, Any],
            self._client.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": mime_type},
                Conditions=[
                    {"Content-Type": mime_type},
                    ["content-length-range", 1, max_size],
                ],
                ExpiresIn=expires_in,
            ),
        )

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether a private S3 object exists."""
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            status_code = exc.response.get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if status_code in {403, 404}:
                return False
            raise
        return True

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        """Download a private S3 object to a local file path."""
        self._client.download_file(bucket, key, destination)


storage = S3Storage()
