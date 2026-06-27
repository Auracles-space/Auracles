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

  it("hides saved searches from non-operators", () => {
    // Saved searches calls an operator-only API; showing the link to admins
    // or other roles bounces them into the onboarding redirect on the 403.
    expect(visibleNavLinks(appLinks, ["admin"]).some(
      (link) => link.href === "/settings/saved-searches",
    )).toBe(false);
    expect(visibleNavLinks(appLinks, ["contributor"]).some(
      (link) => link.href === "/settings/saved-searches",
    )).toBe(false);
  });

  it("shows saved searches to operators", () => {
    expect(visibleNavLinks(appLinks, ["operator"]).some(
      (link) => link.href === "/settings/saved-searches",
    )).toBe(true);
  });

  it("shows the Developer link for developer users", () => {
    const visible = visibleNavLinks(appLinks, ["developer"]);

    expect(visible.some((link) => link.href === "/dashboard/developer")).toBe(
      true,
    );
  });
});
