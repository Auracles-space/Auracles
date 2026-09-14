import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { RequestAttestationLink } from "./request-attestation-link";

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

/** A signed-in viewer with the given roles and id. */
function session(id: string, roles: string[]) {
  return { id, roles, email: "viewer@example.com", display_name: "Viewer" };
}

describe("RequestAttestationLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("links an operator to the prefilled request form", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session("user-2", ["operator"]) as never,
    );

    render(
      <RequestAttestationLink contributorId="user-1" frameworkId="fw-1" />,
    );

    const link = await screen.findByRole("link", {
      name: "Request attestation",
    });
    expect(link).toHaveAttribute("href", "/attestations?target=fw-1");
  });

  it("links a contributor who does not own the framework", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session("user-3", ["contributor"]) as never,
    );

    render(
      <RequestAttestationLink contributorId="user-1" frameworkId="fw-1" />,
    );

    expect(
      await screen.findByRole("link", { name: "Request attestation" }),
    ).toBeInTheDocument();
  });

  it("renders nothing for the framework's own contributor", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session("user-1", ["contributor"]) as never,
    );

    const { container } = render(
      <RequestAttestationLink contributorId="user-1" frameworkId="fw-1" />,
    );

    await waitFor(() => expect(loadCurrentUserSession).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a signed-out visitor", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(null);

    const { container } = render(
      <RequestAttestationLink contributorId="user-1" frameworkId="fw-1" />,
    );

    await waitFor(() => expect(loadCurrentUserSession).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a viewer without an operator or contributor role", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session("user-4", ["attestor"]) as never,
    );

    const { container } = render(
      <RequestAttestationLink contributorId="user-1" frameworkId="fw-1" />,
    );

    await waitFor(() => expect(loadCurrentUserSession).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
