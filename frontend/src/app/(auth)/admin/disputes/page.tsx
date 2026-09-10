/**
 * Authenticated admin dispute route.
 *
 * Both dispute kinds resolve here. They were split across two pages — Project
 * milestone disputes on this route, Attestation disputes buried in the
 * attestation panel — so an admin looking for "disputes" found only half of
 * them. The escrow mechanics differ (Projects settle with release/refund/split
 * amounts; Attestations take a three-outcome verdict), so the panels stay
 * separate; only the route is shared.
 */
import { AdminAttestationDisputesPanel } from "@/components/modules/admin/admin-attestation-disputes-panel";
import { AdminDisputesPanel } from "@/components/modules/admin/admin-disputes-panel";

/**
 * Render the Project and Attestation dispute queues with resolution controls.
 */
export default function AdminDisputesPage() {
  return (
    <div className="grid gap-6">
      <AdminDisputesPanel />
      <AdminAttestationDisputesPanel />
    </div>
  );
}
