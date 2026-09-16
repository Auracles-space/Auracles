/**
 * Attestor offers section: attestation requests routed to the organization,
 * under the approved coverage they were matched on.
 */
import type { Metadata } from "next";

import { AttestationOffersTab } from "@/components/modules/organizations/attestor/attestation-offers-tab";
import { AttestorCoverageSummary } from "@/components/modules/organizations/attestor/attestor-coverage-summary";

export const metadata: Metadata = {
  title: "Attestation Offers | Auracles",
};

export default function OrgAttestorOffersPage() {
  return (
    <div className="space-y-6">
      <AttestorCoverageSummary />
      <AttestationOffersTab />
    </div>
  );
}
