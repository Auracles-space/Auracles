"use client";

import { createContext, useContext, ReactNode, useState } from "react";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

type OrganizationContextType = {
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
  isSuspended: boolean;
  markSuspended: () => void;
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
}: {
  children: ReactNode;
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
  capabilities: MyOrganizationResponse["capabilities"];
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
        isSuspended,
        markSuspended: () => setIsSuspended(true),
      }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}
