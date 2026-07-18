import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";
import { ensureBrowserAccessToken } from "@/lib/auth/current-user-session";

const listFrameworks = vi.fn();
const grantRequiredMessage =
  "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability.";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  ensureBrowserAccessToken: vi.fn(),
}));

vi.mock("@/lib/frameworks/framework-api", () => ({
  CONTRIBUTOR_GRANT_REQUIRED_MESSAGE:
    "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability.",
  frameworkApiFor: vi.fn(() => ({ list: listFrameworks })),
  isFrameworkApiErrorCode: (error: unknown, code: string) =>
    error instanceof Error &&
    "code" in error &&
    error.code === code,
}));

describe("FrameworkList", () => {
  beforeEach(() => {
    listFrameworks.mockReset();
    vi.mocked(ensureBrowserAccessToken).mockReset();
    // Default: a hard reload still has a valid refresh session, so the
    // in-memory access token rehydrates before any data fetch.
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(true);
  });

  it("rehydrates the in-memory access token before fetching frameworks", async () => {
    listFrameworks.mockResolvedValue([]);

    render(
      <FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />,
    );

    await screen.findByText(/no frameworks yet/i);
    expect(ensureBrowserAccessToken).toHaveBeenCalled();
  });

  it("does not call the API when no session can be rehydrated", async () => {
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(false);

    render(
      <FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />,
    );

    expect(await screen.findByText(/session has expired/i)).toBeInTheDocument();
    expect(listFrameworks).not.toHaveBeenCalled();
  });

  it("renders the empty state when the contributor has no frameworks", async () => {
    listFrameworks.mockResolvedValue([]);

    render(
      <FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />,
    );

    expect(await screen.findByText(/no frameworks yet/i)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    listFrameworks.mockRejectedValue(new Error("Frameworks are unavailable."));

    render(
      <FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />,
    );

    expect(
      await screen.findByText(/frameworks are unavailable/i),
    ).toBeInTheDocument();
  });

  it("renders a friendly empty state for a missing organization grant", async () => {
    listFrameworks.mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        code: "capability_grant_required",
      }),
    );

    render(
      <FrameworkList
        seller={{ kind: "org", orgId: "org-1" }}
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    expect(await screen.findByText(grantRequiredMessage)).toBeInTheDocument();
    expect(screen.queryByText(/^request failed$/i)).not.toBeInTheDocument();
  });

  it("lists owned frameworks with status and open link", async () => {
    listFrameworks.mockResolvedValue([
      {
        id: "fw-1",
        title: "Board Risk Operating System",
        status: "published",
        category: "framework",
        version: "1.0.0",
        price: "499.00",
        currency: "USD",
      },
    ]);

    render(
      <FrameworkList
        seller={{ kind: "org", orgId: "org-1" }}
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    expect(
      await screen.findByText(/board risk operating system/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/frameworks/fw-1",
    );
  });
});
