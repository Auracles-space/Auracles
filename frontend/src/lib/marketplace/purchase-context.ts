/**
 * Buyer-context resolution for Framework checkout.
 *
 * Turns the caller's organization memberships into "Buy as" options and routes
 * a purchase to the correct backend call (self vs organization). The client
 * gate here is UX only — the backend re-checks operator capability + admin role.
 */
import { createFrameworkPurchase, createOrgFrameworkPurchase } from "@/lib/generated/sdk.gen";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

export type BuyerOption =
  | { kind: "self"; label: string }
  | { kind: "org"; orgId: string; label: string };

/** Orgs the caller may purchase on behalf of when the framework offers an org tier. */
export function eligibleOrgBuyers(
  orgs: MyOrganizationResponse[],
  offersOrgTier: boolean,
): BuyerOption[] {
  if (!offersOrgTier) {
    return [];
  }
  return orgs
    .filter((o) => (o.role === "admin" || o.role === "owner") && o.capabilities?.operator === "active")
    .map((o) => ({ kind: "org", orgId: o.org.id, label: o.org.name }));
}

/** Self option followed by eligible org buyers. */
export function buyerOptions(
  orgs: MyOrganizationResponse[],
  offersOrgTier: boolean,
): BuyerOption[] {
  return [{ kind: "self", label: "Myself" }, ...eligibleOrgBuyers(orgs, offersOrgTier)];
}

type StartPurchaseArgs = {
  buyer: BuyerOption;
  frameworkId: string;
  licenseType: string;
  headers: Record<string, string>;
};

type PurchaseSession = { clientSecret: string; transactionId: string };

/** Start a purchase transaction as self or as an org; returns a session or an error envelope. */
export async function startPurchase(
  args: StartPurchaseArgs,
): Promise<PurchaseSession | { error: unknown }> {
  const { buyer, frameworkId, licenseType, headers } = args;
  const body = { license_type: licenseType } as never;
  const result =
    buyer.kind === "self"
      ? await createFrameworkPurchase({ body, headers, path: { framework_id: frameworkId } })
      : await createOrgFrameworkPurchase({ body, headers, path: { org_id: buyer.orgId, framework_id: frameworkId } });

  if (!result.response.ok || !result.data) {
    return { error: result.error };
  }
  return { clientSecret: result.data.client_secret, transactionId: result.data.transaction_id };
}
