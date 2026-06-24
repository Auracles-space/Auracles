import { describe, expect, it } from "vitest";

import {
  appLinks,
  visibleNavLinks,
} from "@/components/modules/layout/app-navigation";

describe("visibleNavLinks", () => {
  it("always keeps links marked for any authenticated user", () => {
    const visible = visibleNavLinks(appLinks, []);

    expect(visible.some((link) => link.href === "/explore")).toBe(true);
    expect(visible.some((link) => link.href === "/settings/profile")).toBe(
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

  it("shows the Developer link for developer users", () => {
    const visible = visibleNavLinks(appLinks, ["developer"]);

    expect(visible.some((link) => link.href === "/dashboard/developer")).toBe(
      true,
    );
  });
});
