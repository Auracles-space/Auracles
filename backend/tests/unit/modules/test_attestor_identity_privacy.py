"""Schema-level privacy guard for the org-attestor reviewing member.

Organizations are the attestors; the individual member who performs a review is
org-internal staffing detail. Its identity must never appear on any public or
requestor-facing attestation response schema. Leakage here is a review blocker
per the sub-project spec, so this test introspects the Pydantic model fields of
the public attestation surfaces directly rather than any single serialized
response.
"""

from __future__ import annotations

import inspect

from pydantic import BaseModel

from app.modules.attestation import schemas as attestation_schemas
from app.modules.explore import schemas as explore_schemas
from app.modules.organizations.schemas import OrgAttestationItem

# Any field whose name contains one of these fragments would expose the
# reviewing member who staffed an org attestation.
_FORBIDDEN_FIELD_FRAGMENTS = ("reviewing_member", "reviewer_id")


def _model_classes(module: object) -> list[type[BaseModel]]:
    """Return every Pydantic model defined for a public attestation surface."""
    return [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel
    ]


def test_public_attestation_schemas_hide_reviewing_member() -> None:
    """No public/requestor attestation schema exposes a reviewing-member field."""
    models = _model_classes(attestation_schemas) + _model_classes(explore_schemas)
    assert models  # guard against an empty scan silently passing

    leaks: list[str] = []
    for model in models:
        for field_name in model.model_fields:
            lowered = field_name.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
                leaks.append(f"{model.__name__}.{field_name}")

    assert leaks == [], f"reviewing-member identity leaked on: {leaks}"


def test_org_internal_schema_still_carries_reviewing_member() -> None:
    """Positive control: the org-internal staffing schema keeps the field.

    Guards the leak test above from silently passing if the field is ever
    renamed — the fragment list must still match a real org-internal field.
    """
    assert "reviewing_member_id" in OrgAttestationItem.model_fields
