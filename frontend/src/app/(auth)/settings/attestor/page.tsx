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
    <div className="mx-auto max-w-[1280px] space-y-6">
      <AttestorApplicationPanel />
    </div>
  );
}
