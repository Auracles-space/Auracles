"use client";

/**
 * Capability-sectioned org Financials tab.
 *
 * Composes money-OUT (operator Billing) and money-IN (contributor/attestor
 * Earnings) sections based on the org's active capabilities.
 */
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { OrgBillingSection } from "./org-billing-section";
import { OrgAttestorFinancialsTab } from "@/components/modules/organizations/attestor/org-attestor-financials-tab";

/**
 * Render org financial sections that apply to the org's capabilities.
 *
 * @param props.orgId - Organization id (for the earnings sub-tab).
 */
export function OrgFinancialsTab({ orgId }: { orgId: string }) {
  const { capabilities } = useOrganization();
  const operatorActive = capabilities?.operator === "active";
  const earnsMoney = capabilities?.attestor === "active" || capabilities?.contributor === "active";

  return (
    <div className="grid gap-8">
      {operatorActive && (
        <section>
          <h2 className="px-4 pt-4 font-heading text-xl font-bold text-foreground md:px-6">Billing</h2>
          <OrgBillingSection />
        </section>
      )}
      {earnsMoney && (
        <section>
          <h2 className="px-4 pt-4 font-heading text-xl font-bold text-foreground md:px-6">Earnings</h2>
          <OrgAttestorFinancialsTab orgId={orgId} />
        </section>
      )}
    </div>
  );
}
