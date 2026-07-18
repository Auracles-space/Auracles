/**
 * Organization Framework route composition tests.
 *
 * Verifies route parameters become organization-scoped seller props and the
 * editor derives live-state authority from the existing organization context.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgFrameworkEditor } from "@/components/modules/frameworks/org-framework-editor";
import NewOrgFrameworkPage from "@/app/(auth)/dashboard/organizations/[orgId]/frameworks/new/page";
import OrgFrameworksPage from "@/app/(auth)/dashboard/organizations/[orgId]/frameworks/page";

let organizationRole = "member";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ role: organizationRole }),
}));

vi.mock("@/components/modules/frameworks/framework-list", () => ({
  FrameworkList: (props: {
    basePath: string;
    seller: { kind: string; orgId: string };
  }) => (
    <div
      data-testid="framework-list"
      data-base-path={props.basePath}
      data-org-id={props.seller.orgId}
    />
  ),
}));

vi.mock("@/components/modules/frameworks/create-framework-panel", () => ({
  CreateFrameworkPanel: (props: {
    basePath: string;
    seller: { kind: string; orgId: string };
  }) => (
    <div
      data-testid="create-framework"
      data-base-path={props.basePath}
      data-org-id={props.seller.orgId}
    />
  ),
}));

vi.mock("@/components/modules/frameworks/framework-editor", () => ({
  FrameworkEditor: (props: {
    basePath: string;
    canManageLiveState: boolean;
    frameworkId: string;
    seller: { kind: string; orgId: string };
  }) => (
    <div
      data-testid="framework-editor"
      data-base-path={props.basePath}
      data-can-manage={String(props.canManageLiveState)}
      data-framework-id={props.frameworkId}
      data-org-id={props.seller.orgId}
    />
  ),
}));

describe("organization Framework routes", () => {
  beforeEach(() => {
    organizationRole = "member";
  });

  it("renders the organization-scoped Framework list", async () => {
    render(
      await OrgFrameworksPage({
        params: Promise.resolve({ orgId: "org-1" }),
      }),
    );

    const list = screen.getByTestId("framework-list");
    expect(list).toHaveAttribute("data-org-id", "org-1");
    expect(list).toHaveAttribute(
      "data-base-path",
      "/dashboard/organizations/org-1/frameworks",
    );
  });

  it("renders the organization-scoped create form", async () => {
    render(
      await NewOrgFrameworkPage({
        params: Promise.resolve({ orgId: "org-2" }),
      }),
    );

    const form = screen.getByTestId("create-framework");
    expect(form).toHaveAttribute("data-org-id", "org-2");
    expect(form).toHaveAttribute(
      "data-base-path",
      "/dashboard/organizations/org-2/frameworks",
    );
  });

  it.each([
    ["owner", true],
    ["admin", true],
    ["member", false],
  ])("gates editor live-state controls for a %s", async (role, expected) => {
    organizationRole = role;

    render(<OrgFrameworkEditor id="fw-1" orgId="org-3" />);

    const editor = screen.getByTestId("framework-editor");
    expect(editor).toHaveAttribute("data-can-manage", String(expected));
    expect(editor).toHaveAttribute("data-framework-id", "fw-1");
    expect(editor).toHaveAttribute("data-org-id", "org-3");
  });
});
