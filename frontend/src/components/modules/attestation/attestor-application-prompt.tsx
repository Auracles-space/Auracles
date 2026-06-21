"use client";

/**
 * Attestor application prompt banner.
 *
 * A user who registered with the Attestor role holds it in a pending state
 * until an admin approves their application (the role is standalone and cannot
 * be self-added, so this is the only path in). Until they submit an
 * application, nothing in the role-gated navigation is reachable — so this
 * banner is their entry point to complete it.
 *
 * Renders nothing unless the user has a pending attestor role and has not yet
 * submitted an application.
 *
 * Maps to: FR-ATT-001, FR-ATT-002.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { listMyAttestorApplications } from "@/lib/generated/sdk.gen";

/**
 * Show a call-to-action for pending attestors who have not applied yet.
 */
export function AttestorApplicationPrompt() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    let active = true;
    async function evaluate() {
      const session = await loadCurrentUserSession();
      if (!active || session === null) {
        return;
      }
      if (!session.pending_roles.includes("attestor")) {
        return;
      }
      // Only prompt while no application exists; once submitted the settings
      // page tracks its review status instead.
      const result = await listMyAttestorApplications({
        headers: getAccessTokenHeaders(),
      });
      if (!active || !result.response.ok || !result.data) {
        return;
      }
      setShow(result.data.applications.length === 0);
    }
    void evaluate();
    return () => {
      active = false;
    };
  }, []);

  if (!show) {
    return null;
  }

  return (
    <div className="mx-4 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/30 bg-accent/5 p-4 md:mx-8">
      <div>
        <p className="text-sm font-semibold text-foreground">
          Finish becoming an Attestor
        </p>
        <p className="text-sm text-foreground-muted">
          Submit your application and evidence so an admin can review and approve
          your attestor access.
        </p>
      </div>
      <Link
        className="inline-flex min-h-11 items-center rounded-xl bg-accent px-5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent"
        href="/settings/attestor"
      >
        Complete attestor application
      </Link>
    </div>
  );
}
