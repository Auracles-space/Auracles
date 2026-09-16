import { describe, expect, it } from "vitest";

import { memberSectionFromPath, memberSections } from "./member-sections";

describe("memberSections", () => {
  it("gives an admin the member list, invitations with the pending count, and teams", () => {
    expect(memberSections({ isAdmin: true, counts: { invitations: 2 } })).toEqual([
      { id: "members", label: "Members", count: 0 },
      { id: "invitations", label: "Invitations", count: 2 },
      { id: "teams", label: "Teams", count: 0 },
    ]);
  });

  it("gives a plain member only the member list", () => {
    expect(memberSections({ isAdmin: false, counts: { invitations: 2 } })).toEqual([
      { id: "members", label: "Members", count: 0 },
    ]);
  });
});

describe("memberSectionFromPath", () => {
  const base = "/dashboard/organizations/org-1/members";

  it("reads the member list from the bare tab path and sections from their segment", () => {
    expect(memberSectionFromPath(base, base)).toBe("members");
    expect(memberSectionFromPath(`${base}/invitations`, base)).toBe("invitations");
    expect(memberSectionFromPath(`${base}/teams`, base)).toBe("teams");
  });

  it("returns null for a segment that is not a section", () => {
    expect(memberSectionFromPath(`${base}/unknown`, base)).toBeNull();
  });
});
