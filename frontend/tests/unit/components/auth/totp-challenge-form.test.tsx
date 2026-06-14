import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TotpChallengeForm } from "@/components/modules/auth/totp-challenge-form";
import { setAccessTokenFromJwt } from "@/lib/auth/token-store";
import { verifyTotpLogin } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  verifyTotpLogin: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: { getState: () => ({ roles: ["operator"] }) },
  setAccessTokenFromJwt: vi.fn(),
}));

describe("TotpChallengeForm", () => {
  beforeEach(() => {
    vi.mocked(verifyTotpLogin).mockReset();
    vi.mocked(setAccessTokenFromJwt).mockReset();
  });

  it("exchanges a valid code and routes to the role landing path", async () => {
    const onAuthenticated = vi.fn();
    vi.mocked(verifyTotpLogin).mockResolvedValue({
      data: { access_token: "header.payload.signature" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(
      <TotpChallengeForm challengeToken="ch-1" onAuthenticated={onAuthenticated} />,
    );
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify login/i }));

    await waitFor(() => {
      expect(vi.mocked(setAccessTokenFromJwt)).toHaveBeenCalledWith(
        "header.payload.signature",
      );
      expect(onAuthenticated).toHaveBeenCalledWith("/explore");
    });
  });

  it("honors a safe resume-intent path over the role landing path", async () => {
    const onAuthenticated = vi.fn();
    vi.mocked(verifyTotpLogin).mockResolvedValue({
      data: { access_token: "header.payload.signature" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(
      <TotpChallengeForm
        challengeToken="ch-1"
        next="/library"
        onAuthenticated={onAuthenticated}
      />,
    );
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify login/i }));

    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledWith("/library");
    });
  });

  it("rejects a too-short code before calling the API", async () => {
    render(<TotpChallengeForm challengeToken="ch-1" onAuthenticated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify login/i }));

    expect(await screen.findByText(/enter a valid 2fa code/i)).toBeInTheDocument();
    expect(vi.mocked(verifyTotpLogin)).not.toHaveBeenCalled();
  });

  it("surfaces an invalid-code error from the API", async () => {
    vi.mocked(verifyTotpLogin).mockResolvedValue({
      data: undefined,
      error: { detail: "Invalid 2FA code." },
      response: new Response(null, { status: 401 }),
    });

    render(<TotpChallengeForm challengeToken="ch-1" onAuthenticated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify login/i }));

    expect(await screen.findByText(/invalid 2fa code/i)).toBeInTheDocument();
  });
});
