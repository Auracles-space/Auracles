"use client";

/**
 * Shared organization-naming primitives for the admin money screens.
 *
 * Payouts, payments, the payment trace, and invoices all need to name the
 * organization behind a row (linked to its admin detail page) and fall back
 * to a short user id otherwise, plus an "Organization ID" filter. One module
 * keeps the four surfaces identical.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice D.
 */
import Link from "next/link";
import { useId } from "react";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Check whether a string is a UUID.
 *
 * @param value - Candidate identifier.
 * @returns True for a canonical 36-character UUID.
 */
export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

/**
 * Shorten an identifier for display when no name is available.
 *
 * @param id - Full identifier (usually a UUID).
 * @returns Its first eight characters.
 */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/**
 * Admin detail path for one organization.
 *
 * @param orgId - Organization UUID.
 */
export function adminOrgHref(orgId: string): string {
  return `/admin/organizations/${orgId}`;
}

/**
 * Link to an organization's admin detail page, named when possible.
 *
 * `relative z-10` lets it sit above a row-wide stretched link.
 *
 * @param props.orgId - Organization UUID.
 * @param props.name - Organization name, or null when the API had none.
 */
export function OrgLink({ orgId, name }: { orgId: string; name?: string | null }) {
  return (
    <Link
      className="relative z-10 inline-flex min-h-11 w-fit items-center break-all text-sm font-semibold text-accent hover:underline md:text-xs"
      href={adminOrgHref(orgId)}
      title={orgId}
    >
      {name || shortId(orgId)}
    </Link>
  );
}

/**
 * Name one side of a money movement: the organization if set, else the user.
 *
 * @param props.orgId - Organization UUID, when an organization is the party.
 * @param props.orgName - Organization name from the API.
 * @param props.userId - User UUID, shown shortened when no org is set.
 */
export function PartyName({
  orgId,
  orgName,
  userId,
}: {
  orgId: string | null;
  orgName?: string | null;
  userId: string | null;
}) {
  if (orgId) {
    return <OrgLink name={orgName} orgId={orgId} />;
  }
  if (userId) {
    return (
      <span className="font-mono text-xs text-foreground-muted" title={userId}>
        {shortId(userId)}
      </span>
    );
  }
  return <span className="text-xs text-foreground-subtle">—</span>;
}

/**
 * Organization ID filter with a clear button and inline UUID hint.
 *
 * Callers pass `org_id` to the API only when `isUuid(value)`, so a
 * half-typed id never fires a 422.
 *
 * @param props.value - Current input text.
 * @param props.onChange - Called with the trimmed text.
 */
export function OrgIdFilter({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const invalid = value !== "" && !isUuid(value);
  return (
    <div className="grid gap-2">
      <label className="text-sm font-semibold text-foreground" htmlFor={id}>
        Organization ID
      </label>
      <div className="flex gap-2">
        <input
          aria-describedby={invalid ? `${id}-hint` : undefined}
          aria-invalid={invalid || undefined}
          className="min-h-12 min-w-0 flex-1 rounded-xl border border-border-default bg-background px-4 font-mono text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
          id={id}
          onChange={(event) => onChange(event.target.value.trim())}
          placeholder="Organization UUID"
          value={value}
        />
        {value ? (
          <button
            aria-label="Clear organization filter"
            className="min-h-11 min-w-11 rounded-xl border border-border-default bg-surface-1 px-3 text-sm font-semibold text-foreground transition-colors hover:bg-surface-2"
            onClick={() => onChange("")}
            type="button"
          >
            Clear
          </button>
        ) : null}
      </div>
      {invalid ? (
        <p className="text-xs text-foreground-muted" id={`${id}-hint`}>
          Enter a full organization UUID to filter.
        </p>
      ) : null}
    </div>
  );
}
