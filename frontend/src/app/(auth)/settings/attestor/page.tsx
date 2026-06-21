/**
 * Attestor application route (account settings).
 *
 * Role acquisition lives outside the role-gated `/attestor/*` area so an
 * applicant — who does not yet hold an approved attestor role — can reach it.
 */
import { AttestorApplicationPanel } from "@/components/modules/attestation/attestation-workspaces";

/**
 * Render the Attestor application submission and history.
 */
export default function SettingsAttestorPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <AttestorApplicationPanel />
      </div>
    </main>
  );
}
