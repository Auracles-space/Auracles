"use client";

import { createContext, useContext, ReactNode, useState } from "react";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

type OrganizationContextType = {
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
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
}: {
  children: ReactNode;
  orgId: string;
  role: string;
  org: MyOrganizationResponse["org"];
}) {
  const [isSuspended, setIsSuspended] = useState(false);

  return (
    <OrganizationContext.Provider
      value={{
        orgId,
        role,
        org,
        isSuspended,
        markSuspended: () => setIsSuspended(true),
      }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}
