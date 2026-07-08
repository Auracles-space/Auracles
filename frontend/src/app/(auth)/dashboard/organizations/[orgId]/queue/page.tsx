import { Metadata } from "next";
import { AttestationQueueTab } from "@/components/modules/organizations/attestor/attestation-queue-tab";

export const metadata: Metadata = {
  title: "Attestation Queue | Auracles",
};

export default function OrganizationQueuePage() {
  return (
    <div>
      <AttestationQueueTab />
    </div>
  );
}
