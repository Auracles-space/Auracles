"use client";

/**
 * Entry point that sends an eligible viewer into the Attestation request form
 * with a framework already chosen.
 *
 * The public framework page is unauthenticated SSR and the contributor
 * workspace is shared with org members, so eligibility is resolved in the
 * browser from the in-memory session: a signed-in viewer who is not the
 * framework's own contributor and holds the Operator or Contributor role.
 * Everyone else sees nothing — an owner has no reason to attest their own
 * work through the consent flow, and a viewer without either role cannot pay
 * the fee.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { loadCurrentUserSession } from "@/lib/auth/current-user-session";

/** Roles allowed to commission an attestation. */
const ELIGIBLE_ROLES = ["operator", "contributor"];

const PRIMARY_LINK =
  "mt-3 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent";

const SECONDARY_LINK =
  "mt-3 inline-flex min-h-12 w-full items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 py-2 text-sm font-semibold text-foreground outline-none transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent";

type RequestAttestationLinkProps = {
  /** Framework the request should target. */
  frameworkId: string;
  /** Owner of a personal framework, used to hide the link from the owner. */
  contributorId: string;
  /** Visual weight; `secondary` sits beside another primary action. */
  variant?: "primary" | "secondary";
};

/**
 * Render the "Request attestation" link for viewers who may commission one.
 *
 * @param props - Framework id, its contributor, and the button weight.
 */
export function RequestAttestationLink({
  frameworkId,
  contributorId,
  variant = "primary",
}: RequestAttestationLinkProps) {
  const [eligible, setEligible] = useState(false);

  useEffect(() => {
    let active = true;
    async function resolve() {
      const session = await loadCurrentUserSession();
      if (!active || session === null) {
        return;
      }
      if (session.id === contributorId) {
        return;
      }
      setEligible(
        session.roles.some((role: string) => ELIGIBLE_ROLES.includes(role)),
      );
    }
    void resolve();
    return () => {
      active = false;
    };
  }, [contributorId]);

  if (!eligible) {
    return null;
  }

  return (
    <Link
      className={variant === "secondary" ? SECONDARY_LINK : PRIMARY_LINK}
      href={`/attestations?target=${frameworkId}`}
    >
      Request attestation
    </Link>
  );
}
