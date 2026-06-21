/**
 * Authenticated KYC settings route.
 *
 * Contributors submit identity documents here before payout eligibility.
 */
import { KycUpload } from "@/components/modules/auth/kyc-upload";

export default function KycSettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Identity verification
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Submit identity documents
        </h1>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          KYC documents stay private and are reviewed before contributor
          payout access is granted.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <KycUpload />
      </section>
    </div>
  );
}
