/**
 * Authenticated Attestor application route.
 */
import { AttestorApplicationPanel } from "@/components/modules/attestation/attestation-workspaces";

/**
 * Render Attestor application submission and history.
 */
export default function AttestorApplicationsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <AttestorApplicationPanel />
      </div>
    </main>
  );
}
