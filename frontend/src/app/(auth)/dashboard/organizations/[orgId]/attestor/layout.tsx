/**
 * Attestor tab layout: the application before approval; offers, queue, and
 * application sections once the organization is an attestor.
 */
import type { ReactNode } from "react";

import { AttestorHubLayout } from "@/components/modules/organizations/attestor/attestor-hub-layout";

export default function OrgAttestorLayout({ children }: { children: ReactNode }) {
  return <AttestorHubLayout>{children}</AttestorHubLayout>;
}
