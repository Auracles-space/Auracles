import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/modules/auth/login-form";
import { getCurrentUser, login } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  getCurrentUser: vi.fn(),
  login: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ roles: ["operator"] }),
  },
  setAccessTokenFromJwt: vi.fn(),
}));

describe("LoginForm", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(login).mockReset();
  });

  it("keeps the submit button disabled until email and password are valid", () => {
    render(<LoginForm />);

    const submit = screen.getByRole("button", { name: /^log in$/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "not-an-email" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "secret-pass" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    expect(submit).toBeEnabled();
  });

  it("surfaces generated-client login errors without exposing internals", async () => {
    vi.mocked(login).mockResolvedValue({
      data: undefined,
      error: { detail: "Incorrect email or password." },
      response: new Response(null, { status: 401 }),
    });

    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^log in$/i }));

    expect(
      await screen.findByText(/incorrect email or password/i),
    ).toBeInTheDocument();
  });

  it("routes a 2FA-required login into the challenge step", async () => {
    const onChallenge = vi.fn();
    vi.mocked(login).mockResolvedValue({
      data: {
        challenge_token: "challenge-token",
        expires_in: 900,
        requires_2fa: true,
        token_type: "bearer",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<LoginForm onChallenge={onChallenge} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "CorrectPass123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^log in$/i }));

    await waitFor(() => {
      expect(onChallenge).toHaveBeenCalledWith("challenge-token");
    });
  });

  it("prompts incomplete users to finish onboarding after login", async () => {
    const onAuthenticated = vi.fn();
    vi.mocked(login).mockResolvedValue({
      data: {
        access_token: "header.payload.signature",
        expires_in: 900,
        token_type: "bearer",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: {
        deactivated_at: null,
        display_name: "Ada Markets",
        email: "ada@example.com",
        email_verified: true,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "unverified",
        roles: ["operator"],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<LoginForm onAuthenticated={onAuthenticated} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "CorrectPass123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^log in$/i }));

    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledWith("/settings/onboarding");
    });
  });
});
