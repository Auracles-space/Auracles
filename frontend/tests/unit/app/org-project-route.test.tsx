/**
 * Organization Project workspace route tests.
 *
 * Verifies route parameters select the organization API identity instead of
 * falling back to the personal Project workspace.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import OrgProjectPage from "@/app/(auth)/dashboard/organizations/[orgId]/projects/[id]/page";

vi.mock("@/components/modules/projects/project-workspace", () => ({
  ProjectWorkspace: (props: {
    mode: { kind: string; orgId: string };
    projectId: string;
  }) => (
    <div
      data-testid="project-workspace"
      data-mode={props.mode.kind}
      data-org-id={props.mode.orgId}
      data-project-id={props.projectId}
    />
  ),
}));

describe("organization Project route", () => {
  it("passes both route ids into an org-mode workspace", async () => {
    render(
      await OrgProjectPage({
        params: Promise.resolve({ id: "project-1", orgId: "org-1" }),
      }),
    );

    const workspace = screen.getByTestId("project-workspace");
    expect(workspace).toHaveAttribute("data-mode", "org");
    expect(workspace).toHaveAttribute("data-org-id", "org-1");
    expect(workspace).toHaveAttribute("data-project-id", "project-1");
  });
});
