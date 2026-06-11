/**
 * Authenticated admin Attestation route.
 */
import { AdminAttestationPanel } from "@/components/modules/attestation/attestation-workspaces";

/**
 * Render admin review and resolution controls for Attestation.
 */
export default function AdminAttestationsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <AdminAttestationPanel />
      </div>
    </main>
  );
}
