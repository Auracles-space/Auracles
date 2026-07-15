"""Seed canonical calibration-trial fixtures (idempotent).

Gives a fresh localhost/staging database a startable calibration trial out of
the box: a published ``is_calibration`` Framework, one virus-scanned-clean
artifact uploaded to S3, and a complete answer key for the fixture's rubric.

Idempotent — a fixture already present (matched by its canonical title) is left
untouched, so this is safe to run on every deploy.

Run: ``uv run python -m app.scripts.seed_calibration_fixtures``
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.integrations import s3
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrialAnswerKey,
)
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations import attestor_trial_service as trial_svc

_SEED_OWNER_EMAIL = "calibration-system@auracles.space"

# Canonical fixtures. Each becomes one published, hidden calibration Framework.
_CANONICAL_FIXTURES: tuple[dict[str, str], ...] = (
    {
        "title": "Calibration: Quality Sample",
        "description": (
            "A known-good sample framework used to calibrate new attestors. "
            "Score each rubric dimension against the sample document."
        ),
        "review_type": "quality",
    },
)

# Per-dimension answer-key values applied to every dimension of a fixture's
# rubric. Uniform for the seed; admins tune real fixtures via the curation UI.
_SEED_EXPECTED_SCORE = 4
_SEED_TOLERANCE = 1


def _minimal_pdf(title: str) -> bytes:
    """Return the bytes of a minimal, openable single-page PDF."""
    body = (
        f"BT /F1 18 Tf 40 700 Td ({title}) Tj ET\n"
        "BT /F1 12 Tf 40 660 Td (Calibration trial sample document.) Tj ET"
    )
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            "/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>"
        ),
        f"<</Length {len(body)}>>\nstream\n{body}\nendstream",
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = "%PDF-1.4\n"
    for index, obj in enumerate(objects, start=1):
        out += f"{index} 0 obj\n{obj}\nendobj\n"
    out += "trailer<</Root 1 0 R/Size 6>>\n%%EOF"
    return out.encode("latin-1")


async def _seed_owner(session: AsyncSession) -> User:
    """Return the platform-owned user that owns seeded fixtures, creating it once."""
    owner = await session.scalar(
        select(User).where(User.email == _SEED_OWNER_EMAIL)
    )
    if owner is None:
        owner = User(
            email=_SEED_OWNER_EMAIL,
            password_hash=hash_password(uuid4().hex),
            display_name="Calibration System",
            email_verified=True,
        )
        session.add(owner)
        await session.flush()
    return owner


async def seed_calibration_fixtures(session: AsyncSession) -> list[str]:
    """Create any missing canonical fixtures; return the titles created.

    Args:
        session: An open async session (the caller owns the transaction).

    Returns:
        The titles of fixtures newly created this run (empty if all existed).
    """
    settings = get_settings()
    created: list[str] = []
    owner = await _seed_owner(session)

    for spec in _CANONICAL_FIXTURES:
        existing = await session.scalar(
            select(Framework.id).where(
                Framework.title == spec["title"],
                Framework.is_calibration.is_(True),
            )
        )
        if existing is not None:
            continue

        dimensions = (
            await session.scalars(
                select(AttestationRubricDimension).where(
                    AttestationRubricDimension.review_type == spec["review_type"],
                    AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                )
            )
        ).all()
        if not dimensions:
            logger.bind(
                module="scripts", action="seed_calibration_fixtures"
            ).warning(f"no rubric dimensions for review_type={spec['review_type']}")
            continue

        framework = Framework(
            id=uuid4(),
            contributor_id=owner.id,
            title=spec["title"],
            description=spec["description"],
            version="1.0.0",
            status="published",
            is_calibration=True,
            calibration_review_type=spec["review_type"],
            category=trial_svc._FIXTURE_DEFAULT_CATEGORY,
            sector=trial_svc._FIXTURE_DEFAULT_SECTOR,
            industry=trial_svc._FIXTURE_DEFAULT_INDUSTRY,
            business_function=trial_svc._FIXTURE_DEFAULT_FUNCTION,
            tags=["calibration"],
            tags_text="calibration",
            jurisdiction=trial_svc._FIXTURE_DEFAULT_JURISDICTION,
            complexity=3,
            org_size=trial_svc._FIXTURE_DEFAULT_ORG_SIZE,
            lifecycle_stage=trial_svc._FIXTURE_DEFAULT_LIFECYCLE_STAGE,
            price=trial_svc._FIXTURE_DEFAULT_PRICE,
            currency=trial_svc._FIXTURE_DEFAULT_CURRENCY,
            license_types=trial_svc._FIXTURE_DEFAULT_LICENSE_TYPES,
        )
        session.add(framework)
        await session.flush()

        artifact_id = uuid4()
        file_key = f"frameworks/{framework.id}/artifacts/{artifact_id}.pdf"
        pdf_bytes = _minimal_pdf(spec["title"])
        s3.storage.upload_bytes(
            settings.s3_artifacts_bucket, file_key, pdf_bytes, "application/pdf"
        )
        # Seed content is trusted and deterministic, so mark it scanned-clean
        # directly rather than dispatching the async scanner.
        session.add(
            Artifact(
                id=artifact_id,
                framework_id=framework.id,
                name="Calibration sample.pdf",
                file_key=file_key,
                file_size=len(pdf_bytes),
                mime_type="application/pdf",
                scan_status="clean",
            )
        )
        for dimension in dimensions:
            session.add(
                AttestorTrialAnswerKey(
                    framework_id=framework.id,
                    dimension_id=dimension.id,
                    expected_score=_SEED_EXPECTED_SCORE,
                    tolerance=_SEED_TOLERANCE,
                )
            )
        created.append(spec["title"])

    return created


async def main() -> None:
    """Run the seed inside one transaction and log the outcome."""
    # Import the app so every ORM model is registered before mappers configure;
    # run standalone, this module alone leaves cross-module FKs unresolved.
    import app.main  # noqa: F401

    async with async_session_factory() as session:
        async with session.begin():
            created = await seed_calibration_fixtures(session)
    log = logger.bind(module="scripts", action="seed_calibration_fixtures")
    if created:
        log.info(f"created {len(created)} calibration fixture(s): {created}")
    else:
        log.info("no new calibration fixtures — all canonical fixtures present")


if __name__ == "__main__":
    asyncio.run(main())
