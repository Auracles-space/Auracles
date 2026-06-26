"""Tests for the startup object-storage credential check.

Guards against a mismatched AWS key pair (access key id rotated without its
secret, or vice versa) reaching production, where it silently 403s every
presigned artifact upload with `SignatureDoesNotMatch`. The check fails the
boot loudly instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.integrations.s3 import verify_object_storage


def _settings(environment: str) -> SimpleNamespace:
    """Stub settings carrying only the environment the check reads.

    Avoids the full production Settings validators (TOTP key, etc.) that are
    irrelevant to credential signing.
    """
    return SimpleNamespace(environment=environment)


def test_skips_credential_check_in_local_environment() -> None:
    """Local/dev (LocalStack) must never call out to STS at startup."""
    sts = MagicMock()

    verify_object_storage(_settings("local"), sts_client=sts)

    sts.get_caller_identity.assert_not_called()


def test_passes_when_credentials_are_a_valid_pair() -> None:
    """A signable key pair lets the boot proceed without raising."""
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    verify_object_storage(_settings("production"), sts_client=sts)

    sts.get_caller_identity.assert_called_once()


def test_raises_when_key_pair_signature_is_invalid() -> None:
    """A mismatched key pair (SignatureDoesNotMatch) crashes the boot."""
    sts = MagicMock()
    sts.get_caller_identity.side_effect = ClientError(
        {
            "Error": {
                "Code": "SignatureDoesNotMatch",
                "Message": "The request signature we calculated does not match.",
            }
        },
        "GetCallerIdentity",
    )

    with pytest.raises(RuntimeError, match="matching pair"):
        verify_object_storage(_settings("production"), sts_client=sts)
