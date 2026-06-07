/**
 * Authenticated KYC settings route.
 *
 * Contributors submit identity documents here before payout eligibility.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { KycUpload } from "@/components/modules/auth/kyc-upload";

export default function KycSettingsPage() {
  return (
    <AuthPageShell
      eyebrow="Identity verification"
      summary="KYC documents stay private and are reviewed before contributor payout access is granted."
      title="Submit identity documents for review."
    >
      <KycUpload />
    </AuthPageShell>
  );
}
