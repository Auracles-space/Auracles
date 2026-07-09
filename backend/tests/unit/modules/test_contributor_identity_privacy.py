"""Schema leak guards for public contributor identity surfaces."""

from __future__ import annotations

from types import UnionType
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel

from app.modules.developer.schemas import PartnerFrameworkDetailResponse
from app.modules.explore.schemas import (
    ExploreCatalogResponse,
    ExploreCollectionCard,
    ExploreCollectionDetail,
    ExploreContributorProfile,
    ExploreFrameworkCard,
    ExploreFrameworkDetail,
    ExploreFrameworkListResponse,
)
from app.modules.organizations.schemas import (
    ContributorOrgDirectoryEntry,
    ContributorOrgDirectoryResponse,
)

_BANNED_PUBLIC_FIELDS = {
    "authoring_member_id",
    "delivering_member_id",
    "reviewing_member_id",
    "member_id",
    "member_user_id",
    "org_member_id",
    "user_id",
    "email",
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
    """Return every field name reachable from one public response model."""
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


def test_public_framework_and_directory_schemas_hide_member_identity_fields() -> None:
    """Public framework/explore/directory schemas must not leak member identities."""
    public_models = (
        ExploreFrameworkCard,
        ExploreFrameworkDetail,
        ExploreFrameworkListResponse,
        ExploreCatalogResponse,
        ExploreCollectionCard,
        ExploreCollectionDetail,
        ExploreContributorProfile,
        ContributorOrgDirectoryEntry,
        ContributorOrgDirectoryResponse,
        PartnerFrameworkDetailResponse,
    )

    for model in public_models:
        assert _public_field_names(model).isdisjoint(_BANNED_PUBLIC_FIELDS), (
            model.__name__,
            _public_field_names(model).intersection(_BANNED_PUBLIC_FIELDS),
        )
