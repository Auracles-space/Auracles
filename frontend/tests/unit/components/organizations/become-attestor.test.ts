import { describe, expect, it } from "vitest";

import {
  attestorEntryOrgs,
  eligibleAttestorOrgs,
  resolveAttestorEntry,
} from "@/components/modules/organizations/become-attestor";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

function org(
  id: string,
  role: string,
  capabilities: Record<string, string> = {},
  kybStatus = "verified",
): MyOrganizationResponse {
  return {
    org: { id, name: `Org ${id}`, slug: id, country: "US" },
    role,
    capabilities,
    // Verified by default: an org cannot open an attestor application until
    // it is, so every other case here starts from a verified org.
    kyb_status: kybStatus,
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

  it("excludes an organization that has not been business-verified", () => {
    // Offering it would walk the user into a 403 rather than to the
    // verification page that actually unblocks them.
    const orgs = [
      org("a", "owner"),
      org("b", "owner", {}, "pending"),
      org("c", "owner", {}, "unverified"),
      org("d", "owner", {}, "rejected"),
    ];

    expect(eligibleAttestorOrgs(orgs).map((item) => item.id)).toEqual(["a"]);
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

describe("attestorEntryOrgs", () => {
  it("keeps unverified owner orgs, marked ineligible, so the picker can explain", () => {
    const result = attestorEntryOrgs([
      org("a", "owner"),
      org("b", "owner", {}, "pending"),
      org("c", "member", {}, "pending"),
    ]);

    expect(result.map((item) => [item.id, item.eligible, item.kybStatus])).toEqual([
      ["a", true, "verified"],
      ["b", false, "pending"],
    ]);
  });
});

describe("resolveAttestorEntry", () => {
  it("returns the picker, not create, when the only candidate is still unverified", () => {
    const result = resolveAttestorEntry([org("b", "owner", {}, "pending")]);

    expect(result.kind).toBe("picker");
    if (result.kind === "picker") {
      expect(result.orgs[0]).toMatchObject({ id: "b", eligible: false });
    }
  });

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
