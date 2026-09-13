"use client";

import { createContext, useContext, ReactNode, useState } from "react";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

type OrganizationContextType = {
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
  /** Admin reasons for suspended or revoked capabilities, keyed by capability. */
  capabilityReasons: Record<string, string>;
  /** Business-verification state; everything but verification waits on it. */
  kybStatus: string;
  isSuspended: boolean;
  markSuspended: () => void;
  refreshOrganization: () => Promise<void>;
};

const OrganizationContext = createContext<OrganizationContextType | null>(null);

export function useOrganization() {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error("useOrganization must be used within an OrganizationProvider");
  }
  return context;
}

export function OrganizationProvider({
  children,
  orgId,
  role,
  org,
  capabilities,
  capabilityReasons = {},
  kybStatus = "verified",
  refreshOrganization,
}: {
  children: ReactNode;
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
  capabilityReasons?: Record<string, string>;
  kybStatus?: string;
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
        isSuspended,
        markSuspended: () => setIsSuspended(true),
        refreshOrganization: refreshOrganization ?? (async () => {}),
      }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}
