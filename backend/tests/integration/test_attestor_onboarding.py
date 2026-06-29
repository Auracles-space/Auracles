"""Integration tests for the gated Attestor onboarding flow (Module 1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token

# Reuse shared fixtures/helpers from the existing application test module
# rather than duplicating them. The fixture imports are referenced by name
# (pytest fixture injection + `usefixtures`), which static analysis cannot
# see, hence the targeted noqa.
from tests.integration.test_attestor_applications import (  # noqa: F401
    attestor_application_context,
    create_user,
    migrated_database,
)


@pytest.mark.usefixtures("migrated_database")
async def test_submit_application_starts_submitted_with_taxonomy(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """A submitted application is in 'submitted' state with controlled tags."""
    user_id = await create_user("appl@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={
            "Authorization": (
                f"Bearer {create_access_token(user_id, roles=['contributor'])}"
            )
        },
        json={
            "legal_name": "Jane Q Attestor",
            "linkedin_url": "https://linkedin.com/in/jane",
            "professional_body_numbers": {"cfa_institute": "12345"},
            "sectors": ["PE"],
            "framework_categories": ["Compliance"],
            "jurisdictions": ["US"],
            "credentials_summary": "Twenty years compliance.",
            "sample_work": {},
            "professional_references": "ref",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["sectors"] == ["PE"]
    assert body["framework_categories"] == ["Compliance"]


@pytest.mark.usefixtures("migrated_database")
async def test_submit_rejects_unknown_sector(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Unknown taxonomy values are rejected with 422."""
    user_id = await create_user("appl2@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={
            "Authorization": (
                f"Bearer {create_access_token(user_id, roles=['contributor'])}"
            )
        },
        json={"legal_name": "X", "sectors": ["Crypto"],
              "framework_categories": ["Compliance"], "jurisdictions": ["US"],
              "credentials_summary": "x" * 12, "sample_work": {},
              "professional_references": "r"},
    )
    assert resp.status_code == 422
