"""Guard that every in-app notification link resolves to a real frontend route.

Notification links are plain strings written in backend Python and pushed into
the Next.js router verbatim (`notification-dropdown.tsx` calls `router.push`),
so nothing checks them until a user clicks one and lands on a 404. Six had
rotted that way before this test existed: two were API paths pasted into a
notification, two pointed at a `/attestor/*` surface that was replaced by the
org attestor tab, one wanted a detail page that was never built, and one was a
collection index with only a `[slug]` member.

The test reads the App Router tree directly rather than keeping a list of known
routes, so deleting or renaming a page fails here instead of in a user's
notification tray.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
FRONTEND_APP = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app"

# Functions whose return value is a notification link. Named `*_link` by
# convention across the modules; the auth router's Google landing path is the
# one exception and is listed explicitly.
LINK_FUNCTION_SUFFIXES = ("_link", "_landing_path")

# A link template segment standing in for an interpolated value, e.g. the
# `{org_id}` of `/dashboard/organizations/{org_id}/attestor`.
WILDCARD = "\x00"


def _route_patterns() -> set[tuple[str, ...]]:
    """Return every App Router page as a tuple of path segments.

    Route groups (`(auth)`) contribute no segment, and a dynamic segment
    (`[orgId]`) becomes a wildcard that matches any single value.
    """
    patterns: set[tuple[str, ...]] = set()
    for page in FRONTEND_APP.rglob("page.tsx"):
        segments: list[str] = []
        for part in page.relative_to(FRONTEND_APP).parent.parts:
            if part.startswith("(") and part.endswith(")"):
                continue  # Route group: organizational only, not in the URL.
            segments.append(WILDCARD if part.startswith("[") else part)
        patterns.add(tuple(segments))
    return patterns


def _template(node: ast.expr) -> str | None:
    """Render a string or f-string literal as a path template, else None.

    Interpolated values become the wildcard, so `f"/explore/{id}"` and the
    route `/explore/[id]` compare equal.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        rendered = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                rendered.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                rendered.append(WILDCARD)
            else:  # pragma: no cover - JoinedStr holds only these two types.
                return None
        return "".join(rendered)
    return None


def _collect_links() -> dict[str, list[str]]:
    """Map each frontend-looking link template to where it is written.

    Collects two shapes: a `link=` keyword argument, and a `return` inside a
    function named for producing links. Paths that address our own API rather
    than the frontend are skipped — those are checked by the route tests.
    """
    found: dict[str, list[str]] = {}
    for source in sorted(BACKEND_APP.rglob("*.py")):
        tree = ast.parse(source.read_text(), filename=str(source))
        candidates: list[tuple[ast.expr, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                candidates.extend(
                    (keyword.value, node.lineno)
                    for keyword in node.keywords
                    if keyword.arg == "link"
                )
            elif isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ) and node.name.endswith(LINK_FUNCTION_SUFFIXES):
                candidates.extend(
                    (child.value, child.lineno)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Return) and child.value is not None
                )
        for node, lineno in candidates:
            template = _template(node)
            if template is None or not template.startswith("/"):
                continue
            if template.startswith(("/v1/", "/api/")):
                continue
            relative = source.relative_to(BACKEND_APP.parent)
            found.setdefault(template, []).append(f"{relative}:{lineno}")
    return found


def _resolves(template: str, patterns: set[tuple[str, ...]]) -> bool:
    """Whether a link template matches some App Router page.

    A query string is ignored: it selects state within a page, not the page.
    """
    path = template.split("?", 1)[0].split("#", 1)[0]
    segments = tuple(part for part in path.split("/") if part)
    return any(
        len(segments) == len(pattern)
        and all(
            expected in (actual, WILDCARD)
            for actual, expected in zip(segments, pattern, strict=True)
        )
        for pattern in patterns
    )


def test_frontend_route_tree_is_readable() -> None:
    """The App Router tree must be present, or this guard proves nothing.

    Backend tests run from a full monorepo checkout. If the frontend is ever
    absent, every link would "pass" against an empty route set — so fail loudly
    instead of passing vacuously.
    """
    patterns = _route_patterns()
    assert FRONTEND_APP.is_dir(), f"frontend app router missing at {FRONTEND_APP}"
    assert len(patterns) > 50, f"implausibly few routes found: {len(patterns)}"
    assert ("explore", WILDCARD) in patterns


def test_every_notification_link_resolves_to_a_page() -> None:
    """Every backend-written link must address a page that exists.

    A link that 404s strands the user on the one action the notification was
    sent to prompt, and nothing else in the stack catches it.
    """
    patterns = _route_patterns()
    broken = {
        template: sites
        for template, sites in _collect_links().items()
        if not _resolves(template, patterns)
    }
    assert not broken, "notification links with no matching page: " + "; ".join(
        f"{template} ({', '.join(sites)})" for template, sites in sorted(broken.items())
    )
