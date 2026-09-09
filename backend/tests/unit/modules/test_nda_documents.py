"""Unit tests for platform NDA document loading.

The document a member signs is selected by ``ORG_MEMBER_NDA_VERSION``, so the
loader's failure mode matters: a version bump that forgets its document must
not quietly present a blank agreement for signature.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.organizations.nda_service import (
    MissingNdaDocumentError,
    nda_document_text,
)


def test_configured_version_has_a_document() -> None:
    """The version the app is configured to serve must exist on disk."""
    text = nda_document_text(get_settings().org_member_nda_version)

    assert "Confidential Information" in text


def test_missing_version_raises_rather_than_returning_nothing() -> None:
    """An unpublished version fails loudly instead of signing empty text."""
    with pytest.raises(MissingNdaDocumentError):
        nda_document_text("9.9-does-not-exist")


@pytest.mark.parametrize(
    "version",
    ["../__init__", "/etc/passwd", "", "1.0/../../secrets"],
)
def test_version_cannot_traverse_out_of_the_document_directory(version: str) -> None:
    """The version reaches the filesystem, so it is refused unless plain."""
    with pytest.raises(MissingNdaDocumentError):
        nda_document_text(version)
