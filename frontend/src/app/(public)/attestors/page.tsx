import { Metadata } from "next";
import Link from "next/link";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { listAttestorOrgs } from "@/lib/generated/sdk.gen";
import { AttestorOrgCard } from "@/components/modules/attestation/directory/attestor-org-card";

export const metadata: Metadata = {
  title: "Attestor Directory",
  description: "Browse verified organizations authorized to perform attestations.",
};

export default async function AttestorsPage() {
  configureServerMarketplaceClient();
  
  let attestors = [];
  let unavailable = false;

  try {
    const result = await listAttestorOrgs();
    if (!result.response.ok || !result.data) {
      unavailable = true;
    } else {
      attestors = result.data.attestors;
    }
  } catch {
    unavailable = true;
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-4xl font-bold font-heading text-foreground">Attestor Directory</h1>
          <p className="text-foreground-muted text-lg">
            Browse verified organizations authorized to perform attestations.
          </p>
        </div>
        <Link 
          href="/dashboard/organizations"
          className="inline-flex h-10 shrink-0 items-center justify-center rounded-control bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90"
        >
          Become an Attestor
        </Link>
      </div>

      {unavailable ? (
        <div className="rounded-xl border border-warning/30 bg-warning/10 p-8 text-center">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Directory is temporarily unavailable
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            The attestor directory will return when the API is reachable.
          </p>
        </div>
      ) : attestors.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-12 text-center text-foreground-muted">
          No attestors found.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {attestors.map((attestor) => (
            <AttestorOrgCard key={attestor.org_id} org={attestor} />
          ))}
        </div>
      )}
    </main>
  );
}
