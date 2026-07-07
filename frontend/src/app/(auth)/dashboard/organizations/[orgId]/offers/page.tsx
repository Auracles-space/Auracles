import { Metadata } from "next";
import { AttestationOffersTab } from "@/components/modules/organizations/attestor/attestation-offers-tab";

export const metadata: Metadata = {
  title: "Attestation Offers | Auracles",
};

export default function OrganizationOffersPage() {
  return (
    <div>
      <AttestationOffersTab />
    </div>
  );
}
