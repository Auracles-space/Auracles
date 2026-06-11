"""Constants shared across Developer platform services and schemas."""

VALID_API_KEY_SCOPES = frozenset(
    {
        "catalog:read",
        "preview:read",
        "attestations:read",
        "purchase:write",
        "purchases:read",
    }
)

VALID_PARTNER_WEBHOOK_EVENTS = frozenset(
    {
        "purchase.confirmed",
        "commission.cleared",
        "framework.updated",
    }
)
