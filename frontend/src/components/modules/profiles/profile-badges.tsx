/**
 * Profile trust + role badges.
 *
 * Shared between the public profile page and the owner editor. Verification is
 * the visual reward on Auracles, so the KYC seal uses the brand accent while
 * role badges stay quiet and semantic.
 */


type UserRole = "admin" | "attestor" | "contributor" | "operator";

const ROLE_STYLES: Record<UserRole, string> = {
  admin: "bg-surface-2 border-border-default text-foreground font-semibold",
  attestor: "bg-surface-2 border-border-default text-foreground-muted",
  contributor: "bg-surface-2 border-border-default text-foreground-muted",
  operator: "bg-surface-2 border-border-default text-foreground-muted",
};

const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  attestor: "Attestor",
  contributor: "Contributor",
  operator: "Operator",
};

/**
 * Render a semantic role badge.
 *
 * @param role - Raw role identifier from the profile payload.
 */
export function RoleBadge({ role }: { role: string }) {
  const normalized = role.toLowerCase() as UserRole;
  const styles =
    ROLE_STYLES[normalized] ??
    "bg-surface-2 border-border-default text-foreground-muted";
  const label = ROLE_LABELS[normalized] ?? role;

  return (
    <span
      className={`inline-flex h-7 items-center rounded-badge border px-2.5 text-xs font-medium uppercase tracking-[0.05em] ${styles}`}
    >
      {label}
    </span>
  );
}

/**
 * Render the verified-identity seal shown only when KYC is verified.
 *
 * @param verified - Whether the profile owner has completed identity checks.
 */
export function KycSeal({ verified }: { verified: boolean }) {
  if (!verified) {
    return null;
  }
  return (
    <span className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border-default bg-surface-1 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-accent shadow-sm">
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
      Verified
    </span>
  );
}
