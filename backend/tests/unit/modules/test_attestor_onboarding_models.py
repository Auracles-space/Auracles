"""Model-level tests for Attestor onboarding columns and the trials table."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.modules.attestation.models import AttestorApplication, AttestorTrial
from app.modules.auth.models import User


@pytest.mark.usefixtures("migrated_database")
async def test_application_persists_onboarding_fields_and_trial() -> None:
    """An application stores taxonomy + CoI fields and links a trial row."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="t-models@example.com",
                password_hash=hash_password("CorrectHorse9"),
                display_name="t",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            appn = AttestorApplication(
                user_id=user.id,
                status="submitted",
                legal_name="Jane Q Attestor",
                # Legacy column predating Task 1's `sectors`/`framework_categories`
                # taxonomy; still NOT NULL with no server default on this model,
                # so it must be supplied explicitly here.
                specializations=[],
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="x" * 12,
                sample_work={},
                professional_references="ref",
                coi_declarations=[
                    {
                        "entity": "Acme",
                        "entity_type": "firm",
                        "relationship": "employment",
                        "within_24mo": True,
                    }
                ],
            )
            session.add(appn)
            await session.flush()
            session.add(
                AttestorTrial(application_id=appn.id, status="assigned", attempt=1)
            )
        loaded = await session.scalar(
            select(AttestorApplication).where(AttestorApplication.id == appn.id)
        )
        assert loaded.sectors == ["PE"]
        assert loaded.coi_declarations[0]["entity"] == "Acme"
