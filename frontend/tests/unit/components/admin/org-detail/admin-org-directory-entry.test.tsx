/**
 * The admin organization directory links each organization to its detail page
 * in both the phone card and the md+ table row.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AdminOrgCard,
  AdminOrgTableRow,
} from "@/components/modules/admin/admin-org-directory-entry";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";

const ORG = {
  id: "org-1",
  slug: "kano-audit",
  name: "Kano Audit Partners",
  country: "NG",
  member_count: 4,
  capabilities: { operator: "active" },
  kyb_status: "verified",
  created_at: "2026-09-01T09:00:00Z",
} as AdminOrgResponse;

describe("admin organization directory entry", () => {
  it("links the organization name on the phone card to the detail page", () => {
    render(
      <ul>
        <AdminOrgCard onAction={vi.fn()} onCapabilities={vi.fn()} org={ORG} />
      </ul>,
    );
    expect(screen.getByRole("link", { name: "Kano Audit Partners" })).toHaveAttribute(
      "href",
      "/admin/organizations/org-1",
    );
  });

  it("links the organization name in the table row to the detail page", () => {
    render(
      <table>
        <tbody>
          <AdminOrgTableRow onAction={vi.fn()} onCapabilities={vi.fn()} org={ORG} />
        </tbody>
      </table>,
    );
    expect(screen.getByRole("link", { name: "Kano Audit Partners" })).toHaveAttribute(
      "href",
      "/admin/organizations/org-1",
    );
  });
});
