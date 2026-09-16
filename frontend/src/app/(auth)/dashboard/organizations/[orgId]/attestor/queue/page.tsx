/**
 * Attestor queue section: the organization's accepted reviews and history.
 */
import type { Metadata } from "next";

import { AttestationQueueTab } from "@/components/modules/organizations/attestor/attestation-queue-tab";

export const metadata: Metadata = {
  title: "Attestation Queue | Auracles",
};

export default function OrgAttestorQueuePage() {
  return <AttestationQueueTab />;
}
