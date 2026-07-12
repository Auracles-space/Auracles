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
    ]);
    expect(result.map((o) => (o.kind === "org" ? o.orgId : "self"))).toEqual(["a", "d"]);
  });
});

describe("buyerOptions", () => {
  it("prepends a self option", () => {
    const result = buyerOptions([org("a", "admin", "active")]);
    expect(result[0]).toEqual({ kind: "self", label: "Myself" });
    expect(result).toHaveLength(2);
  });
});

describe("startPurchase", () => {
  const okEnvelope = { data: { client_secret: "cs", transaction_id: "tx" }, error: undefined, response: { ok: true } };

  it("routes a self purchase through createFrameworkPurchase", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: { Authorization: "Bearer t" } });
    expect(sdk.createFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "team" }, path: { framework_id: "fw" } }),
    );
    expect(res).toEqual({ clientSecret: "cs", transactionId: "tx" });
  });

  it("routes an org purchase through createOrgFrameworkPurchase with org_id", async () => {
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    await startPurchase({ buyer: { kind: "org", orgId: "org-9", label: "Org 9" }, frameworkId: "fw", licenseType: "organizational", headers: {} });
    expect(sdk.createOrgFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "organizational" }, path: { org_id: "org-9", framework_id: "fw" } }),
    );
  });

  it("returns the error envelope on failure", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue({ data: undefined, error: { detail: "x" }, response: { ok: false } } as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: {} });
    expect(res).toEqual({ error: { detail: "x" } });
  });
});
