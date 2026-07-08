import { Metadata } from "next";
import { notFound } from "next/navigation";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { getAttestorOrg, listAttestorOrgCompleted } from "@/lib/generated/sdk.gen";
import { AttestorOrgProfile } from "@/components/modules/attestation/directory/attestor-org-profile";
import { CredentialStatusBadge } from "@/components/modules/attestation/credential-status-badge";
import Link from "next/link";
import { formatRelativeTime } from "@/lib/marketplace/format";

type PageProps = {
  params: Promise<{ orgId: string }>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { orgId } = await params;
  configureServerMarketplaceClient();
  
  try {
    const result = await getAttestorOrg({ path: { org_id: orgId } });
    if (result.data) {
      return {
        title: `${result.data.name} | Attestor Directory`,
        description: `View the attestor profile and completed attestations for ${result.data.name}.`,
      };
    }
  } catch {}

  return {
    title: "Attestor Profile | Attestor Directory",
  };
}

export default async function AttestorProfilePage({ params }: PageProps) {
  const { orgId } = await params;
  configureServerMarketplaceClient();

  let profile;
  let completedAttestations = [];

  try {
    const [profileRes, completedRes] = await Promise.all([
      getAttestorOrg({ path: { org_id: orgId } }),
      listAttestorOrgCompleted({ path: { org_id: orgId } }),
    ]);

    if (!profileRes.response.ok || !profileRes.data) {
      return notFound();
    }
    
    profile = profileRes.data;
    if (completedRes.response.ok && completedRes.data) {
      completedAttestations = completedRes.data;
    }
  } catch {
    return notFound();
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">
      <div className="mb-4">
        <Link href="/attestors" className="text-sm font-medium text-foreground-muted hover:text-foreground transition-colors">
          &larr; Back to Directory
        </Link>
      </div>

      <AttestorOrgProfile org={profile} />

      <section className="space-y-6 pt-8">
        <h2 className="text-2xl font-bold font-heading text-foreground">Completed Attestations</h2>
        
        {completedAttestations.length === 0 ? (
          <div className="rounded-xl border border-border-default bg-surface-1 p-8 text-center text-foreground-muted">
            No completed attestations yet.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {completedAttestations.map((attestation) => (
              <div 
                key={attestation.id} 
                className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm space-y-4"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h3 className="font-semibold text-foreground truncate">
                      {attestation.target_title}
                    </h3>
                    <p className="text-xs text-foreground-muted uppercase tracking-wider mt-1">
                      {attestation.target_type}
                    </p>
                  </div>
                  <CredentialStatusBadge status={attestation.status as any} />
                </div>
                
                <div className="pt-3 border-t border-border-default flex justify-between items-center text-sm">
                  <span className="text-foreground-muted">
                    {attestation.published_at 
                      ? formatRelativeTime(new Date(attestation.published_at)) 
                      : 'Unknown date'}
                  </span>
                  <Link 
                    href={`/explore/${attestation.target_id}`} 
                    className="text-accent hover:underline font-medium"
                  >
                    View Framework
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
