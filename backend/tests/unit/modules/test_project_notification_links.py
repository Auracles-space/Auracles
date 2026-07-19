"""Project notification deep-link tests.

Operator-side notifications must deep-link org-operated Projects to their
organization route. An org owner has no individual-Operator access, so the
plain ``/projects/{id}`` link resolves to "Project is not visible to this
user"; the org route is the only page they can open.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.projects import notifications as project_notifications


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record queued Project notification dispatches without Celery/Redis."""
    calls: list[dict[str, Any]] = []

    class _FakeTask:
        def delay(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        project_notifications, "dispatch_project_notification", _FakeTask()
    )
    return calls


def test_operator_notification_links_org_project_to_org_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org-operated Project links the Operator to its organization route."""
    calls = _capture(monkeypatch)
    org_id = uuid4()
    project_id = uuid4()

    project_notifications.notify_milestone_plan_finalized(
        operator_id=uuid4(),
        project_id=project_id,
        operator_org_id=org_id,
    )

    assert len(calls) == 1
    assert (
        calls[0]["link"]
        == f"/dashboard/organizations/{org_id}/projects/{project_id}"
    )


def test_operator_notification_links_individual_project_to_plain_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An individually-operated Project keeps the plain workspace route."""
    calls = _capture(monkeypatch)
    project_id = uuid4()

    project_notifications.notify_milestone_plan_finalized(
        operator_id=uuid4(),
        project_id=project_id,
        operator_org_id=None,
    )

    assert len(calls) == 1
    assert calls[0]["link"] == f"/projects/{project_id}"
