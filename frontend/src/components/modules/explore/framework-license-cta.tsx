"use client";

/**
 * Framework license call-to-action.
 *
 * Replaces the static "License Framework" link with a viewer-aware control on
 * the public framework detail page. The page itself is unauthenticated SSR, so
 * this client component resolves the viewer from the in-memory session and
 * adapts:
 *   - the framework's own contributor sees no license button (it's theirs);
 *   - an operator who already holds an active license is sent to their library;
 *   - everyone else (incl. signed-out visitors) sees the license link.
 *
 * Maps to: FR-FIN-003, FR-FWK-014.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { listOperatorLibrary } from "@/lib/generated/sdk.gen";
import type { LibraryItem } from "@/lib/generated/types.gen";

type CtaState = "loading" | "owner" | "licensed" | "available";

type FrameworkLicenseCtaProps = {
  frameworkId: string;
  /** Owner of the framework, used to detect the viewer-is-owner case. */
  contributorId: string;
};

const PRIMARY_LINK =
  "mt-6 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-accent px-4 py-2 text-sm font-bold tracking-wide text-white shadow-[0_4px_14px_0_rgba(199,70,52,0.39)] outline-none transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

/**
 * Render the appropriate license action for the current viewer.
 */
export function FrameworkLicenseCta({
  frameworkId,
  contributorId,
}: FrameworkLicenseCtaProps) {
  const [state, setState] = useState<CtaState>("loading");

  useEffect(() => {
    let active = true;
    async function resolve() {
      const session = await loadCurrentUserSession();
      if (!active) {
        return;
      }
      // Signed out: the license link doubles as the entry point (checkout gates
      // role/KYC and bounces anonymous visitors to login).
      if (session === null) {
        setState("available");
        return;
      }
      if (session.id === contributorId) {
        setState("owner");
        return;
      }
      // Only operators can hold a license, so only they need the library check.
      if (!session.roles.includes("operator")) {
        setState("available");
        return;
      }
      const result = await listOperatorLibrary({
        headers: getAccessTokenHeaders(),
      });
      if (!active) {
        return;
      }
      const licensed =
        result.response.ok &&
        result.data?.items.some(
          (item: LibraryItem) => item.framework_id === frameworkId,
        );
      setState(licensed ? "licensed" : "available");
    }
    void resolve();
    return () => {
      active = false;
    };
  }, [contributorId, frameworkId]);

  if (state === "loading") {
    return <div className="mt-6 h-12 w-full animate-pulse rounded-xl bg-surface-2" />;
  }

  if (state === "owner") {
    return (
      <div className="mt-6 rounded-xl border border-border-default bg-surface-1 px-4 py-3 text-center text-sm font-semibold text-foreground-muted">
        This is your framework.{" "}
        <Link
          className="text-accent hover:underline"
          href={`/dashboard/frameworks/${frameworkId}`}
        >
          Manage it
        </Link>
      </div>
    );
  }

  if (state === "licensed") {
    return (
      <Link className={PRIMARY_LINK} href="/library">
        View in your library
      </Link>
    );
  }

  return (
    <Link className={PRIMARY_LINK} href={`/checkout/${frameworkId}`}>
      License Framework
    </Link>
  );
}
