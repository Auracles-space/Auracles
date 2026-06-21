import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttestorApplicationPrompt } from "@/components/modules/attestation/attestor-application-prompt";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { listMyAttestorApplications } from "@/lib/generated/sdk.gen";
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return { ...actual, getAccessTokenHeaders: vi.fn(() => ({})) };
});

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyAttestorApplications: vi.fn(),
}));

const okResponse = new Response(null, { status: 200 });

function session(overrides: Partial<CurrentUserResponse> = {}): CurrentUserResponse {
  return {
    avatar_url: null,
    deactivated_at: null,
    display_name: "User",
    email: "user@auracles.test",
    email_verified: true,
    id: "user-1",
    kyc_status: "unverified",
    pending_roles: [],
    roles: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(loadCurrentUserSession).mockReset();
  vi.mocked(listMyAttestorApplications).mockReset();
});

describe("AttestorApplicationPrompt", () => {
  it("prompts a pending attestor who has not applied", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session({ pending_roles: ["attestor"] }),
    );
    vi.mocked(listMyAttestorApplications).mockResolvedValue({
      data: { applications: [] },
      error: undefined,
      response: okResponse,
    } as never);

    render(<AttestorApplicationPrompt />);

    const link = await screen.findByRole("link", {
      name: /complete attestor application/i,
    });
    expect(link).toHaveAttribute("href", "/settings/attestor");
  });

  it("stays hidden once an application exists", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session({ pending_roles: ["attestor"] }),
    );
    vi.mocked(listMyAttestorApplications).mockResolvedValue({
      data: { applications: [{ id: "app-1" }] },
      error: undefined,
      response: okResponse,
    } as never);

    render(<AttestorApplicationPrompt />);

    await waitFor(() =>
      expect(listMyAttestorApplications).toHaveBeenCalledTimes(1),
    );
    expect(
      screen.queryByRole("link", { name: /complete attestor application/i }),
    ).not.toBeInTheDocument();
  });

  it("stays hidden for users without a pending attestor role", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session({ roles: ["operator"] }),
    );

    render(<AttestorApplicationPrompt />);

    await waitFor(() =>
      expect(loadCurrentUserSession).toHaveBeenCalledTimes(1),
    );
    expect(listMyAttestorApplications).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("link", { name: /complete attestor application/i }),
    ).not.toBeInTheDocument();
  });
});
