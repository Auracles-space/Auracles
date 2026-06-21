/**
 * Authenticated Credential settings route.
 */
import { CredentialManager } from "@/components/modules/attestation/credential-manager";

/**
 * Render user-owned Credentials for Attestation targets.
 */
export default function CredentialsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <CredentialManager />
    </div>
  );
}
