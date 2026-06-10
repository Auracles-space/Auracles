/**
 * Authenticated Attestor assignments route.
 */
import { AttestorAssignmentsPanel } from "@/components/modules/attestation/attestation-workspaces";

/**
 * Render Attestor offer and report workflow.
 */
export default function AttestorAssignmentsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <AttestorAssignmentsPanel />
      </div>
    </main>
  );
}
