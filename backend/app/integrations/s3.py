"""S3 adapter for private Auracles object storage."""

from __future__ import annotations

from typing import Any, cast

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)
from loguru import logger

from app.core.config import Settings, get_settings


def _aws_client_kwargs(settings: Settings) -> dict[str, Any]:
    """Assemble boto3 client kwargs (region, credentials, endpoint) from settings.

    Shared by the S3 client and the startup STS credential check so both sign
    with the exact same key pair and endpoint.

    Args:
        settings: Application settings holding AWS credentials and region.

    Returns:
        Keyword arguments suitable for ``boto3.client``.
    """
    kwargs: dict[str, Any] = {"region_name": settings.aws_default_region}
    if settings.aws_access_key_id is not None:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
    if settings.aws_secret_access_key is not None:
        kwargs["aws_secret_access_key"] = (
            settings.aws_secret_access_key.get_secret_value()
        )
    if settings.aws_endpoint_url is not None:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return kwargs


def verify_object_storage(
    settings: Settings,
    *,
    sts_client: Any | None = None,
) -> None:
    """Fail the boot fast if AWS credentials are not a valid signing pair.

    A rotated secret left paired with a stale access key id (or vice versa)
    produces ``SignatureDoesNotMatch`` on every presigned upload, silently
    breaking artifact ingestion in production. STS ``get_caller_identity``
    requires no IAM permission, so it isolates credential validity from bucket
    authorization and surfaces the mismatch at startup instead.

    Skipped entirely in the ``local`` environment (dev/LocalStack/tests).

    Args:
        settings: Application settings (environment + AWS credentials).
        sts_client: Optional pre-built STS client, for testing.

    Raises:
        RuntimeError: If the credentials cannot sign an STS request.
    """
    if settings.environment == "local":
        return

    if sts_client is None:
        import boto3  # type: ignore[import-untyped]

        sts_client = boto3.client("sts", **_aws_client_kwargs(settings))

    try:
        sts_client.get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(
            "AWS credential check failed at startup: "
            f"{exc}. Verify AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are a "
            "matching pair (a rotated secret needs its own access key id)."
        ) from exc

    logger.bind(module="integrations", action="verify_object_storage").info(
        "aws_credentials_verified"
    )


class S3Storage:
    """Small wrapper around S3 operations used by request services."""

    def __init__(self) -> None:
        """Create an S3 client from application settings."""
        settings = get_settings()
        import boto3

        self._client = boto3.client("s3", **_aws_client_kwargs(settings))

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

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Upload bytes to a private S3 object."""
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=mime_type,
        )

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        """Download a private S3 object to a local file path."""
        self._client.download_file(bucket, key, destination)

    def copy_object(
        self,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> None:
        """Copy one private S3 object to another private S3 key."""
        self._client.copy_object(
            Bucket=destination_bucket,
            Key=destination_key,
            CopySource={"Bucket": source_bucket, "Key": source_key},
        )

    def delete_object(self, bucket: str, key: str) -> None:
        """Delete one private S3 object."""
        self._client.delete_object(Bucket=bucket, Key=key)

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Create a short-lived GET URL for a private S3 object."""
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if download_name is not None:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{download_name}"'
            )
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        )


storage = S3Storage()
