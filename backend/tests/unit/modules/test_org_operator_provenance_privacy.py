"""Schema leak guards for org-operator provenance fields.

Task 9 keeps org-internal staffing and allocation provenance out of buyer,
Contributor, and public response models. These tests recurse the relevant
response schemas so future field additions cannot accidentally expose
``granted_by``, grant-target member ids, or posting/reviewing member ids.
"""

from __future__ import annotations

from types import UnionType
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel

from app.modules.frameworks.schemas import (
    FrameworkReviewListResponse,
    FrameworkReviewResponse,
)
from app.modules.library.schemas import LibraryItem, LibraryResponse
from app.modules.organizations.schemas import OrgLibraryItem, OrgLibraryResponse
from app.modules.projects.schemas import ProjectResponse, ProjectsResponse

_BANNED_PROVENANCE_FIELDS = {
    "granted_by",
    "member_id",
    "posting_member_id",
    "reviewing_member_id",
}


def _nested_models(annotation: Any) -> set[type[BaseModel]]:
    """Return nested Pydantic models reachable from one field annotation."""
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return {annotation}
        return set()
    if origin in {list, tuple, set, frozenset, Annotated, UnionType}:
        models: set[type[BaseModel]] = set()
        for arg in get_args(annotation):
            models.update(_nested_models(arg))
        return models
    if origin is dict:
        models: set[type[BaseModel]] = set()
        for arg in get_args(annotation):
            models.update(_nested_models(arg))
        return models
    return set()


def _public_field_names(root: type[BaseModel]) -> set[str]:
    """Return every reachable field name from one response model."""
    seen_models: set[type[BaseModel]] = set()
    pending = [root]
    names: set[str] = set()
    while pending:
        model = pending.pop()
        if model in seen_models:
            continue
        seen_models.add(model)
        names.update(model.model_fields.keys())
        for field_info in model.model_fields.values():
            pending.extend(_nested_models(field_info.annotation))
    return names


def test_org_operator_public_and_buyer_schemas_hide_provenance_fields() -> None:
    """Buyer/public org-operator schemas must not expose internal provenance."""
    response_models = (
        LibraryItem,
        LibraryResponse,
        OrgLibraryItem,
        OrgLibraryResponse,
        FrameworkReviewResponse,
        FrameworkReviewListResponse,
        ProjectResponse,
        ProjectsResponse,
    )

    for model in response_models:
        assert _public_field_names(model).isdisjoint(_BANNED_PROVENANCE_FIELDS), (
            model.__name__,
            _public_field_names(model).intersection(_BANNED_PROVENANCE_FIELDS),
        )
