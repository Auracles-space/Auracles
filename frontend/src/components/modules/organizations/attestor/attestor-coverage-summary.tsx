"use client";

/**
 * Approved coverage of an attestor organization, shown above its offers.
 *
 * Matching offers the org requests in the sectors, functions, and
 * jurisdictions it was approved for, so this summary explains why the offers
 * below arrived. It replaces the application record once the org is approved:
 * the rest of the application has nothing left to do. Renders nothing when
 * the application cannot be loaded, so it never blocks the offers themselves.
 */
import { useEffect, useState } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { getOrgAttestorApplication } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";
import {
  FUNCTION_OPTIONS,
  JURISDICTION_OPTIONS,
  SECTOR_OPTIONS,
  type MarketplaceOption,
} from "@/lib/marketplace/taxonomy";

type Coverage = Pick<OrgAttestorApplicationResponse, "sectors" | "functions" | "jurisdictions">;

/**
 * Label taxonomy values, falling back to title case for retired values.
 *
 * @param values - Stored taxonomy slugs.
 * @param options - The taxonomy the slugs come from.
 */
function labelsFor(
  values: readonly string[] | null | undefined,
  options: readonly MarketplaceOption[],
): string[] {
  return (values ?? []).map(
    (value) => options.find((option) => option.value === value)?.label ?? formatLabel(value),
  );
}

/**
 * Render the approved-coverage summary for the current organization.
 */
export function AttestorCoverageSummary() {
  const { orgId } = useOrganization();
  const [coverage, setCoverage] = useState<Coverage | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load(): Promise<void> {
      const res = await getOrgAttestorApplication({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (mounted && res.data) setCoverage(res.data);
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [orgId]);

  if (!coverage) return null;

  const rows = [
    { label: "Sectors", values: labelsFor(coverage.sectors, SECTOR_OPTIONS) },
    { label: "Functions", values: labelsFor(coverage.functions, FUNCTION_OPTIONS) },
    { label: "Jurisdictions", values: labelsFor(coverage.jurisdictions, JURISDICTION_OPTIONS) },
  ];

  return (
    <section
      aria-labelledby="attestor-coverage-heading"
      className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm sm:p-5"
    >
      <h2
        className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted"
        id="attestor-coverage-heading"
      >
        Approved coverage
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Offers are matched on what your organization was approved to attest.
      </p>
      <dl className="mt-4 grid gap-3 md:grid-cols-3">
        {rows.map((row) => (
          <div className="rounded-xl bg-surface-2 p-3" key={row.label}>
            <dt className="text-xs font-semibold text-foreground">{row.label}</dt>
            <dd className="mt-2 flex flex-wrap gap-1.5">
              {row.values.length > 0 ? (
                row.values.map((value) => (
                  <span
                    className="inline-flex min-h-7 items-center rounded-badge border border-border-default bg-surface-1 px-2.5 text-xs text-foreground"
                    key={value}
                  >
                    {value}
                  </span>
                ))
              ) : (
                <span className="text-xs text-foreground-muted">None recorded</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
