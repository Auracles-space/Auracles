/**
 * Attestor application section: the application record once the organization
 * is an attestor.
 */
import type { Metadata } from "next";

import { AttestorApplicationTab } from "@/components/modules/organizations/attestor/attestor-application-tab";

export const metadata: Metadata = {
  title: "Attestor Application | Auracles",
};

export default function OrgAttestorApplicationPage() {
  return <AttestorApplicationTab />;
}
