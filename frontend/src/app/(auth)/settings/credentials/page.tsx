/**
 * Authenticated Credential settings route.
 */
import { CredentialManager } from "@/components/modules/attestation/credential-manager";

/**
 * Render user-owned Credentials for Attestation targets.
 */
export default function CredentialsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <CredentialManager />
      </div>
    </main>
  );
}
