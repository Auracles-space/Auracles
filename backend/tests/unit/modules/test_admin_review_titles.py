"""Admin review notices name what needs attention.

Every notice used to read "Item awaiting admin review", so an admin could not
tell an attestor application from a project dispute before opening it.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.admin import notifications


def test_admin_review_titles_name_the_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known domains get a specific title; unknown ones keep the generic one."""
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        notifications,
        "dispatch_admin_notification",
        SimpleNamespace(delay=lambda **kwargs: sent.append(kwargs)),
    )

    for domain in (
        "org_attestor_application",
        "project_dispute",
        "org_kyb",
        "brand_new",
    ):
        notifications.notify_admins_review_pending(
            domain=domain, target_id=uuid4(), body="body", link="/admin"
        )

    assert [item["title"] for item in sent] == [
        "Attestor application submitted",
        "Project dispute raised",
        "Business verification submitted",
        "Item awaiting admin review",
    ]
