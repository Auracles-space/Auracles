"""Static guards for marketplace multi-row transaction boundaries.

These checks intentionally enforce a project code standard: write paths that
touch domain rows plus audit rows must declare an explicit SQLAlchemy
transaction boundary instead of relying on implicit session behavior.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable

from app.modules.admin import service as admin_service
from app.modules.frameworks import service as framework_service
from app.modules.library import service as library_service


def _source(function: Callable[..., object]) -> str:
    """Return normalized source for a service function under review."""
    module = inspect.getmodule(function)
    if not module or not module.__file__:
        return inspect.getsource(function)
    with open(module.__file__) as f:
        source_code = f.read()

    parsed = ast.parse(source_code)
    for node in ast.walk(parsed):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name == function.__name__
        ):
            return ast.get_source_segment(source_code, node) or inspect.getsource(
                function
            )
    return inspect.getsource(function)


def test_publish_framework_uses_explicit_transaction_boundary() -> None:
    """Publishing writes Framework, version snapshot, version artifacts, and audit."""
    assert "async with db.begin()" in _source(framework_service.publish_framework)


def test_acknowledge_soft_fail_uses_explicit_transaction_boundary() -> None:
    """Soft-fail acknowledgement writes rarity audit, Framework state, and audit."""
    assert "async with db.begin()" in _source(framework_service.acknowledge_soft_fail)


def test_request_artifact_download_uses_explicit_transaction_boundary() -> None:
    """Download requests write download audit rows and security audit rows."""
    assert "async with db.begin()" in _source(library_service.request_artifact_download)


def test_grant_license_uses_explicit_transaction_boundary() -> None:
    """Admin license grants write License rows and audit rows atomically."""
    assert "async with db.begin()" in _source(admin_service.grant_license)
