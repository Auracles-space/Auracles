import { describe, expect, it } from "vitest";

import {
  appLinks,
  visibleNavLinks,
} from "@/components/modules/layout/app-navigation";

describe("visibleNavLinks", () => {
  it("always keeps links marked for any authenticated user", () => {
    const visible = visibleNavLinks(appLinks, []);

    expect(visible.some((link) => link.href === "/explore")).toBe(true);
    expect(visible.some((link) => link.href === "/settings/identity")).toBe(
      true,
    );
  });

  it("hides admin-only links from non-admin users", () => {
    const visible = visibleNavLinks(appLinks, ["operator"]);

    expect(visible.some((link) => link.href === "/admin/analytics")).toBe(false);
  });

  it("shows the union of operator and contributor navigation", () => {
    const visible = visibleNavLinks(appLinks, ["operator", "contributor"]);

    expect(visible.some((link) => link.href === "/dashboard/frameworks")).toBe(
      true,
    );
    expect(visible.some((link) => link.href === "/library")).toBe(true);
    expect(visible.some((link) => link.href === "/projects")).toBe(true);
  });

  it("keeps the attestor directory out of the nav for every role", () => {
    // Requestors reach it from the attestation workspace, where they are
    // choosing a verifier. It was shown to every role, attestors included.
    for (const roles of [["contributor"], ["operator"], ["attestor"], ["admin"]]) {
      expect(
        visibleNavLinks(appLinks, roles).some((link) => link.href === "/attestors"),
      ).toBe(false);
    }
  });

  it("keeps collections out of the nav for every role", () => {
    // A Collection is a bundle of Frameworks, so the builder is a tab of the
    // Frameworks workspace; /dashboard/collections redirects to that tab.
    for (const roles of [["contributor"], ["operator"], ["admin"]]) {
      expect(
        visibleNavLinks(appLinks, roles).some(
          (link) => link.href === "/dashboard/collections",
        ),
      ).toBe(false);
    }
  });

  it("keeps saved searches out of the nav for every role", () => {
    // Saved searches are created on Explore and listed there beside the button
    // that creates them; the settings page stays reachable from that list and
    // from Settings, so it no longer earns a nav slot of its own.
    for (const roles of [["operator"], ["contributor"], ["admin"]]) {
      expect(
        visibleNavLinks(appLinks, roles).some(
          (link) => link.href === "/settings/saved-searches",
        ),
      ).toBe(false);
    }
  });

  it("shows the Developer link for developer users", () => {
    const visible = visibleNavLinks(appLinks, ["developer"]);

    expect(visible.some((link) => link.href === "/dashboard/developer")).toBe(
      true,
    );
  });
});

describe("visibleNavLinks order", () => {
  // Most used first: the marketplace entry, then each role's daily work,
  // then periodic management, then occasional tools; Settings stays last.
  it("orders a contributor's links from most to least used", () => {
    expect(visibleNavLinks(appLinks, ["contributor"]).map((link) => link.label)).toEqual([
      "Explore",
      "Frameworks",
      "Projects",
      "Attestations",
      "Financials",
      "Organizations",
      "Developer",
      "Settings",
    ]);
  });

  it("orders an operator's links from most to least used", () => {
    expect(visibleNavLinks(appLinks, ["operator"]).map((link) => link.label)).toEqual([
      "Explore",
      "Library",
      "Projects",
      "Attestations",
      "Organizations",
      "Settings",
    ]);
  });

  it("keeps Admin just above Settings for administrators", () => {
    const labels = visibleNavLinks(appLinks, ["admin"]).map((link) => link.label);
    expect(labels.slice(-2)).toEqual(["Admin", "Settings"]);
  });
});
