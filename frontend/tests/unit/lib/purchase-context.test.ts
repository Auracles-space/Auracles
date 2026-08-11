import { describe, expect, it, vi } from "vitest";
import { buyerOptions, eligibleOrgBuyers, startPurchase } from "@/lib/marketplace/purchase-context";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
  createOrgFrameworkPurchase: vi.fn(),
}));

const org = (id: string, role: string, operator: string) =>
  ({ org: { id, name: `Org ${id}` }, role, capabilities: { operator } }) as never;

describe("eligibleOrgBuyers", () => {
  it("includes only admin/owner orgs with active operator capability", () => {
    const result = eligibleOrgBuyers([
      org("a", "admin", "active"),
      org("b", "member", "active"),
      org("c", "owner", "suspended"),
      org("d", "owner", "active"),
    ], true);
    expect(result.map((o) => (o.kind === "org" ? o.orgId : "self"))).toEqual(["a", "d"]);
  });

  it("returns no org buyers when the framework does not offer the org tier", () => {
    expect(eligibleOrgBuyers([org("a", "admin", "active")], false)).toHaveLength(0);
  });
});

describe("buyerOptions", () => {
  it("prepends a self option", () => {
    const result = buyerOptions([org("a", "admin", "active")], false);
    expect(result[0]).toEqual({ kind: "self", label: "Myself" });
    expect(result).toHaveLength(1);
  });
});

describe("startPurchase", () => {
  const okEnvelope = { data: { provider: "stripe", client_secret: "cs", transaction_id: "tx" }, error: undefined, response: { ok: true } };
  const paystackEnvelope = { data: { provider: "paystack", authorization_url: "https://checkout.paystack.com/ref_1", transaction_id: "tx" }, error: undefined, response: { ok: true } };

  it("routes a self purchase through createFrameworkPurchase", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: { Authorization: "Bearer t" } });
    expect(sdk.createFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "team" }, path: { framework_id: "fw" } }),
    );
    expect(res).toEqual({ kind: "stripe", clientSecret: "cs", transactionId: "tx" });
  });

  it("routes an org purchase through createOrgFrameworkPurchase with org_id", async () => {
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    await startPurchase({ buyer: { kind: "org", orgId: "org-9", label: "Org 9" }, frameworkId: "fw", licenseType: "organizational", headers: {} });
    expect(sdk.createOrgFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "organizational" }, path: { org_id: "org-9", framework_id: "fw" } }),
    );
  });

  it("returns a paystack session carrying the hosted checkout URL", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue(paystackEnvelope as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: {}, country: "NG" });
    expect(sdk.createFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "team", country: "NG" } }),
    );
    expect(res).toEqual({ kind: "paystack", authorizationUrl: "https://checkout.paystack.com/ref_1", transactionId: "tx" });
  });

  it("reports an error when paystack returns no redirect URL", async () => {
    // There is no in-page fallback on this rail, so a missing URL is fatal
    // rather than something to degrade around.
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue({ data: { provider: "paystack", authorization_url: null, transaction_id: "tx" }, error: undefined, response: { ok: true } } as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: {}, country: "NG" });
    expect(res).toEqual({ error: { detail: "Checkout could not be started." } });
  });

  it("returns the error envelope on failure", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue({ data: undefined, error: { detail: "x" }, response: { ok: false } } as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: {} });
    expect(res).toEqual({ error: { detail: "x" } });
  });
});
