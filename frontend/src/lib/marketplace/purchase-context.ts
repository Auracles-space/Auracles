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
  /** ISO 3166-1 alpha-2 billing country; omitted sends no country at all. */
  country?: string;
};

/**
 * How the chosen provider expects checkout to continue.
 *
 * Stripe confirms in-page against a client secret; Paystack takes over on its
 * own hosted page. The two are mutually exclusive, so the caller discriminates
 * on `kind` rather than testing which field happens to be present.
 */
export type PurchaseSession =
  | { kind: "stripe"; clientSecret: string; transactionId: string }
  | { kind: "paystack"; authorizationUrl: string; transactionId: string };

/** Start a purchase transaction as self or as an org; returns a session or an error envelope. */
export async function startPurchase(
  args: StartPurchaseArgs,
): Promise<PurchaseSession | { error: unknown }> {
  const { buyer, frameworkId, licenseType, headers, country } = args;
  const body = {
    license_type: licenseType,
    ...(country ? { country } : {}),
  } as never;
  const result =
    buyer.kind === "self"
      ? await createFrameworkPurchase({ body, headers, path: { framework_id: frameworkId } })
      : await createOrgFrameworkPurchase({ body, headers, path: { org_id: buyer.orgId, framework_id: frameworkId } });

  if (!result.response.ok || !result.data) {
    return { error: result.error };
  }

  const transactionId = result.data.transaction_id;
  if (result.data.provider === "paystack") {
    // A Paystack response without a URL is unusable — there is no in-page
    // fallback to degrade to — so surface it rather than rendering a dead form.
    if (!result.data.authorization_url) {
      return { error: { detail: "Checkout could not be started." } };
    }
    return {
      kind: "paystack",
      authorizationUrl: result.data.authorization_url,
      transactionId,
    };
  }
  if (!result.data.client_secret) {
    return { error: { detail: "Checkout could not be started." } };
  }
  return { kind: "stripe", clientSecret: result.data.client_secret, transactionId };
}
