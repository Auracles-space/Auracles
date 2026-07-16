import { describe, it, expect } from "vitest";

import { appLinks, visibleNavLinks } from "./app-navigation";

/** Extract the hrefs visible to a given active role set. */
function visibleHrefs(roles: string[]): string[] {
  return visibleNavLinks(appLinks, roles).map((link) => link.href);
}

describe("visibleNavLinks — Attestations link", () => {
  it("shows the Attestations link to contributors", () => {
    expect(visibleHrefs(["contributor"])).toContain("/attestations");
  });

  it("shows the Attestations link to operators", () => {
    expect(visibleHrefs(["operator"])).toContain("/attestations");
  });

  it("hides the Attestations link from attestor-only users", () => {
    expect(visibleHrefs(["attestor"])).not.toContain("/attestations");
  });
});
