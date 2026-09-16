/**
 * Attestor offers section: attestation requests routed to the organization.
 */
import type { Metadata } from "next";

import { AttestationOffersTab } from "@/components/modules/organizations/attestor/attestation-offers-tab";

export const metadata: Metadata = {
  title: "Attestation Offers | Auracles",
};

export default function OrgAttestorOffersPage() {
  return <AttestationOffersTab />;
}
