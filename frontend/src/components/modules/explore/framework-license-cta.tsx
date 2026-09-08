"use client";

/**
 * Framework license call-to-action.
 *
 * Replaces the static "License Framework" link with a viewer-aware control on
 * the public framework detail page. The page itself is unauthenticated SSR, so
 * this client component resolves the viewer from the in-memory session and
 * adapts:
 *   - the framework's own contributor sees no license button (it's theirs);
 *   - a member of the framework's owning organization sees no license button
 *     (it's their org's) — org frameworks have no single contributor id, so
 *     ownership is matched on the organization instead;
 *   - an operator who already holds an active license is sent to their library;
 *   - everyone else (incl. signed-out visitors) sees the license link.
 *
 * Maps to: FR-FIN-003, FR-FWK-014.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  listMyOrganizationsV1OrgsMineGet,
  listOperatorLibrary,
} from "@/lib/generated/sdk.gen";
import type {
  LibraryItem,
  MyOrganizationResponse,
} from "@/lib/generated/types.gen";

type CtaState =
  | "loading"
  | "owner"
  | "org_owner"
  | "licensed"
  | "needs_operator_role"
  | "available";

type FrameworkLicenseCtaProps = {
  frameworkId: string;
  /** Owner of a personal framework, used to detect the viewer-is-owner case. */
  contributorId: string;
  /** Owning organization of an org framework, for the viewer-is-member case. */
  contributorOrgId?: string;
};

const PRIMARY_LINK =
  "mt-6 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-accent px-4 py-2 text-sm font-bold tracking-wide text-white shadow-[0_4px_14px_0_rgba(199,70,52,0.39)] outline-none transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

const OWNER_NOTICE =
  "mt-6 rounded-xl border border-border-default bg-surface-1 px-4 py-3 text-center text-sm font-semibold text-foreground-muted";

/**
 * Render the appropriate license action for the current viewer.
 */
export function FrameworkLicenseCta({
  frameworkId,
  contributorId,
  contributorOrgId,
}: FrameworkLicenseCtaProps) {
  const [state, setState] = useState<CtaState>("loading");
  // Framework detail is a public SSR route; the current path is the return
  // destination after a role is added.
  const pathname = usePathname() ?? `/explore/${frameworkId}`;

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
      // Org frameworks carry no single contributor id; match the viewer against
      // the owning organization so no member is prompted to buy their own org's
      // framework.
      if (contributorOrgId) {
        const orgs = await listMyOrganizationsV1OrgsMineGet({
          headers: getAccessTokenHeaders(),
        });
        if (!active) {
          return;
        }
        const isMember =
          orgs.response.ok &&
          orgs.data?.organizations.some(
            (membership: MyOrganizationResponse) =>
              membership.org.id === contributorOrgId,
          );
        if (isMember) {
          setState("org_owner");
          return;
        }
      }
      // Only operators can hold a license, so only they need the library check.
      // A signed-in non-operator cannot buy at all — /checkout is role-guarded
      // — so send them to the role rather than into that wall.
      if (!session.roles.includes("operator")) {
        setState("needs_operator_role");
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
  }, [contributorId, contributorOrgId, frameworkId]);

  if (state === "loading") {
    return <div className="mt-6 h-12 w-full animate-pulse rounded-xl bg-surface-2" />;
  }

  if (state === "owner") {
    return (
      <div className={OWNER_NOTICE}>
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

  if (state === "org_owner") {
    return (
      <div className={OWNER_NOTICE}>
        This is your organization&apos;s framework.{" "}
        <Link
          className="text-accent hover:underline"
          href={`/dashboard/organizations/${contributorOrgId}/frameworks/${frameworkId}`}
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

  if (state === "needs_operator_role") {
    return (
      <>
        <Link
          className={PRIMARY_LINK}
          href={`/settings/roles?next=${encodeURIComponent(pathname)}`}
        >
          Become an Operator to license
        </Link>
        <p className="mt-2 text-center text-xs leading-5 text-foreground-muted">
          Licensing is an Operator action. Adding the role takes a moment and
          keeps everything you already have.
        </p>
      </>
    );
  }

  return (
    <Link className={PRIMARY_LINK} href={`/checkout/${frameworkId}`}>
      License Framework
    </Link>
  );
}
