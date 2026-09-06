"""Tests that presigned uploads address the bucket's own region.

boto3 defaults `generate_presigned_post` to the legacy global endpoint
(`<bucket>.s3.amazonaws.com`). For a bucket outside us-east-1 — ours is in
eu-west-2 — S3 answers that with `307 TemporaryRedirect`, so the browser
re-sends the whole file to the regional host. The upload still completes, which
is why this hid: it costs a second full upload of every artifact rather than
failing outright.

Guards the fix — `addressing_style="virtual"` on the boto3 client — against a
silent regression. Note it is the addressing style that does this, not
`signature_version`; that was measured, both being set is belt and braces.
The LocalStack case is covered too, because virtual addressing there would
produce a hostname that does not resolve.
"""

from __future__ import annotations

import boto3

from app.core.config import Settings
from app.integrations.s3 import _aws_client_kwargs


def _client(region: str):
    """Build an S3 client exactly as the app does, for `region`."""
    settings = Settings(
        AWS_DEFAULT_REGION=region,
        AWS_ACCESS_KEY_ID="AKIAQAPROBEKEYEXAMPLE",
        AWS_SECRET_ACCESS_KEY="qa-probe-secret-not-a-real-key",
        AWS_ENDPOINT_URL=None,
    )
    return boto3.client("s3", **_aws_client_kwargs(settings))


def test_presigned_post_targets_the_regional_endpoint() -> None:
    """The upload URL must name the bucket's region, not the global endpoint.

    A global-endpoint URL yields 307 TemporaryRedirect from eu-west-2, which
    doubles the bytes uploaded for every artifact.
    """
    post = _client("eu-west-2").generate_presigned_post(
        "auracles-artifacts-staging", "frameworks/x/artifacts/y.pdf", ExpiresIn=900
    )

    assert post["url"] == (
        "https://auracles-artifacts-staging.s3.eu-west-2.amazonaws.com/"
    )
    assert ".s3.amazonaws.com" not in post["url"]


def test_presigned_post_policy_still_signs_with_sigv4() -> None:
    """Pinning the endpoint must not drop the SigV4 policy fields."""
    post = _client("eu-west-2").generate_presigned_post(
        "auracles-artifacts-staging", "frameworks/x/artifacts/y.pdf", ExpiresIn=900
    )

    assert post["fields"]["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    assert "eu-west-2" in post["fields"]["x-amz-credential"]
    assert post["fields"]["key"] == "frameworks/x/artifacts/y.pdf"


def test_explicit_endpoint_url_still_wins() -> None:
    """LocalStack must keep working: an explicit endpoint overrides the region."""
    settings = Settings(
        AWS_DEFAULT_REGION="eu-west-2",
        AWS_ACCESS_KEY_ID="test",
        AWS_SECRET_ACCESS_KEY="test",
        AWS_ENDPOINT_URL="http://localhost:4566",
    )
    client = boto3.client("s3", **_aws_client_kwargs(settings))

    post = client.generate_presigned_post("bucket", "key.pdf", ExpiresIn=900)

    assert post["url"].startswith("http://localhost:4566")
