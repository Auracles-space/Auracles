"use client";

/**
 * Organization context shared by every tab under the organization shell.
 *
 * Carries the membership entry from `GET /v1/orgs/mine` (org, caller role,
 * capabilities, verification state) plus live suspension state so children
 * never refetch what the shell already loaded.
 */
import { createContext, useContext, ReactNode, useState } from "react";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

type OrganizationContextType = {
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
  /** Admin reasons for suspended or revoked capabilities, keyed by capability. */
  capabilityReasons: Record<string, string>;
  /** Business-verification state; capabilities wait on it. */
  kybStatus: string;
  /** When business verification was approved, or null when not verified. */
  kybVerifiedAt: string | null;
  /** Number of members, or null when the API entry does not carry it yet. */
  memberCount: number | null;
  /** Attention counts (offers, queue, invitations) from the membership entry. */
  counts: MyOrganizationResponse["counts"];
  isSuspended: boolean;
  markSuspended: () => void;
  refreshOrganization: () => Promise<void>;
};

const OrganizationContext = createContext<OrganizationContextType | null>(null);

/** Read the organization context; throws outside an `OrganizationProvider`. */
export function useOrganization() {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error("useOrganization must be used within an OrganizationProvider");
  }
  return context;
}

/**
 * Provide the organization membership to the shell's children.
 *
 * @param props - Membership entry fields plus an optional refetch callback.
 */
export function OrganizationProvider({
  children,
  orgId,
  role,
  org,
  capabilities,
  capabilityReasons = {},
  kybStatus = "verified",
  kybVerifiedAt = null,
  memberCount = null,
  counts,
  refreshOrganization,
}: {
  children: ReactNode;
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
  capabilityReasons?: Record<string, string>;
  kybStatus?: string;
  kybVerifiedAt?: string | null;
  memberCount?: number | null;
  counts?: MyOrganizationResponse["counts"];
  refreshOrganization?: () => Promise<void>;
}) {
  // Seed from the org's persisted suspension state so the banner shows on load;
  // markSuspended() lets a child that hits a 403 org_suspended flip it live.
  const [isSuspended, setIsSuspended] = useState(!!org.suspended_at);

  return (
    <OrganizationContext.Provider
      value={{
        orgId,
        role,
        org,
        capabilities,
        capabilityReasons,
        kybStatus,
        kybVerifiedAt,
        memberCount,
        counts,
        isSuspended,
        markSuspended: () => setIsSuspended(true),
        refreshOrganization: refreshOrganization ?? (async () => {}),
      }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}
