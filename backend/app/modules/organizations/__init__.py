"""Organizations Core module.

Org entity, membership roles, invitations, teams, and the capability
status skeleton consumed by the org-as-attestor/contributor/operator
sub-projects. See docs/superpowers/specs/2026-07-03-organizations-core-design.md.
"""

from app.modules.organizations import attestor_trial_service

__all__ = ["attestor_trial_service"]
