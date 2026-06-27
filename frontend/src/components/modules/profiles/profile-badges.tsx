/**
 * Profile trust + role badges.
 *
 * Shared between the public profile page and the owner editor. Verification is
 * the visual reward on Auracles, so the KYC seal uses the brand accent while
 * role badges stay quiet and semantic.
 */
import { CheckCircledIcon } from "@radix-ui/react-icons";

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
    <span className="inline-flex h-7 items-center gap-1.5 rounded-badge border border-accent/20 bg-accent/5 px-2.5 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
      <CheckCircledIcon className="h-3.5 w-3.5" aria-hidden="true" />
      Verified identity
    </span>
  );
}
