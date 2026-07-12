import { describe, expect, it } from "vitest";

import {
  eligibleAttestorOrgs,
  resolveAttestorEntry,
} from "@/components/modules/organizations/become-attestor";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

function org(
  id: string,
  role: string,
  capabilities: Record<string, string> = {},
): MyOrganizationResponse {
  return {
    org: { id, name: `Org ${id}`, slug: id, country: "US" },
    role,
    capabilities,
  } as MyOrganizationResponse;
}

describe("eligibleAttestorOrgs", () => {
  it("keeps owner and admin orgs that are not already active attestors", () => {
    const orgs = [
      org("a", "owner"),
      org("b", "admin", { attestor: "pending" }),
      org("c", "member"),
      org("d", "owner", { attestor: "active" }),
    ];

    expect(eligibleAttestorOrgs(orgs).map((item) => item.id)).toEqual(["a", "b"]);
  });

  it("carries the attestor capability status for display", () => {
    const result = eligibleAttestorOrgs([
      org("a", "owner"),
      org("b", "admin", { attestor: "pending" }),
    ]);

    expect(result[0]).toMatchObject({ id: "a", attestorStatus: null });
    expect(result[1]).toMatchObject({ id: "b", attestorStatus: "pending" });
  });
});

describe("resolveAttestorEntry", () => {
  it("returns create when there are no eligible orgs", () => {
    expect(resolveAttestorEntry([org("d", "owner", { attestor: "active" })])).toEqual({
      kind: "create",
    });
    expect(resolveAttestorEntry([org("c", "member")])).toEqual({ kind: "create" });
    expect(resolveAttestorEntry([])).toEqual({ kind: "create" });
  });

  it("returns direct when exactly one org is eligible", () => {
    expect(resolveAttestorEntry([org("a", "owner"), org("c", "member")])).toEqual({
      kind: "direct",
      orgId: "a",
    });
  });

  it("returns picker when two or more orgs are eligible", () => {
    const result = resolveAttestorEntry([org("a", "owner"), org("b", "admin")]);

    expect(result.kind).toBe("picker");
    if (result.kind === "picker") {
      expect(result.orgs.map((item) => item.id)).toEqual(["a", "b"]);
    }
  });
});
