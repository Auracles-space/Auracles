/**
 * Public organization profile (SSR).
 *
 * Renders the public-safe fields of one organization by slug: identity,
 * description, member count, join date, and active capabilities through the
 * shared status vocabulary. The website link is rendered only for http(s)
 * URLs so a stored `javascript:` value can never become a clickable href.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { Metadata } from "next";
import { notFound } from "next/navigation";
import { getPublicOrgV1OrgsSlugGet } from "@/lib/generated/sdk.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { StatusPill } from "@/components/ui/status-pill";
import { capabilityLabel } from "@/components/modules/organizations/capability-labels";

import { GlobeIcon, CalendarIcon, PersonIcon } from "@radix-ui/react-icons";

/** Accept only absolute http(s) URLs as a clickable website. */
function httpWebsite(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined;
}

interface Props {
  params: Promise<{ slug: string }>;
}

/** Build the page title and description from the public org record. */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  // Server renders have no browser origin; without the API base URL the
  // generated client throws and every slug reads as not found.
  configureServerMarketplaceClient();
  try {
    const res = await getPublicOrgV1OrgsSlugGet({ path: { slug } });
    if (!res.response.ok || !res.data) {
      return { title: "Organization Not Found - Auracles" };
    }
    return {
      title: `${res.data.name} - Auracles`,
      description: res.data.description || `Public profile for ${res.data.name}`,
    };
  } catch {
    return { title: "Organization Not Found - Auracles" };
  }
}

/**
 * Render the public profile for the organization at `/orgs/[slug]`.
 *
 * @param props - Route params carrying the organization slug.
 */
export default async function PublicOrganizationPage({ params }: Props) {
  const { slug } = await params;
  configureServerMarketplaceClient();

  let org;
  try {
    const res = await getPublicOrgV1OrgsSlugGet({ path: { slug } });
    if (!res.response.ok || !res.data) {
      notFound();
    }
    org = res.data;
  } catch {
    notFound();
  }

  const joinDate = new Date(org.created_at).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric"
  });
  const website = httpWebsite(org.website);

  return (
    <div className="min-h-screen bg-background pt-24 pb-16">
      <main className="container max-w-4xl px-4 sm:px-6">
        <div className="rounded-3xl border border-border-default bg-surface-1 shadow-sm overflow-hidden">
          {/* Cover Photo Area (Solid Color) */}
          <div className="h-32 sm:h-48 bg-accent/10 relative">
            {/* Logo Avatar */}
            <div className="absolute -bottom-12 left-6 sm:left-8">
              <div className="flex h-24 w-24 sm:h-28 sm:w-28 items-center justify-center overflow-hidden rounded-2xl border-4 border-surface-1 bg-surface-2 text-3xl font-heading font-bold text-foreground shadow-sm">
                {org.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={org.logo_url}
                    alt={`${org.name} logo`}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  org.name.charAt(0).toUpperCase()
                )}
              </div>
            </div>
          </div>
          
          <div className="px-6 sm:px-8 pb-8 pt-16">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div>
                <h1 className="font-heading text-2xl sm:text-3xl font-bold text-foreground">
                  {org.name}
                </h1>
                <p className="text-foreground-muted">
                  @{org.slug} • {org.country}
                </p>
              </div>
              
              <div className="flex gap-2">
                {website && (
                  <ButtonLink href={website} target="_blank" rel="noopener noreferrer">
                    <GlobeIcon className="mr-2 h-4 w-4" />
                    Website
                  </ButtonLink>
                )}
              </div>
            </div>

            <div className="mt-6">
              {org.description ? (
                <p className="whitespace-pre-wrap text-foreground max-w-3xl leading-relaxed">
                  {org.description}
                </p>
              ) : (
                <p className="italic text-foreground-muted">
                  No description provided.
                </p>
              )}
            </div>

            <div className="mt-8 flex flex-wrap gap-4 text-sm text-foreground-muted">
              <div className="flex items-center gap-1.5">
                <PersonIcon className="h-4 w-4" />
                {org.member_count} {org.member_count === 1 ? "Member" : "Members"}
              </div>
              <div className="flex items-center gap-1.5">
                <CalendarIcon className="h-4 w-4" />
                Joined {joinDate}
              </div>
            </div>

            {org.active_capabilities.length > 0 && (
              <div className="mt-8 border-t border-border-default pt-6">
                <h3 className="mb-4 font-heading text-sm font-semibold uppercase tracking-wider text-foreground-muted">
                  Capabilities
                </h3>
                <div className="flex flex-wrap gap-2">
                  {org.active_capabilities.map((cap: string) => (
                    <StatusPill key={cap} label={capabilityLabel(cap)} status="active" />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

/** Secondary-style anchor with a 44px touch target. */
function ButtonLink({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      {...props}
      className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {children}
    </a>
  );
}
