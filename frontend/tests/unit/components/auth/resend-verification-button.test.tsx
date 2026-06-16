import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResendVerificationButton } from "@/components/modules/auth/resend-verification-button";
import { resendVerificationV1AuthResendVerificationPost } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  resendVerificationV1AuthResendVerificationPost: vi.fn(),
}));

describe("ResendVerificationButton", () => {
  beforeEach(() => {
    vi.mocked(resendVerificationV1AuthResendVerificationPost).mockReset();
  });

  it("disables the button when the email is invalid", () => {
    render(<ResendVerificationButton email="not-an-email" />);

    expect(
      screen.getByRole("button", { name: /resend verification email/i }),
    ).toBeDisabled();
  });

  it("resends the verification email for a valid address", async () => {
    vi.mocked(resendVerificationV1AuthResendVerificationPost).mockResolvedValue({
      data: { message: "If email is new, verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ResendVerificationButton email="ada@example.com" />);
    fireEvent.click(
      screen.getByRole("button", { name: /resend verification email/i }),
    );

    await waitFor(() => {
      expect(
        vi.mocked(resendVerificationV1AuthResendVerificationPost),
      ).toHaveBeenCalledWith({ body: { email: "ada@example.com" } });
    });
    expect(await screen.findByText(/verification sent/i)).toBeInTheDocument();
  });

  it("surfaces an error when the resend request fails", async () => {
    vi.mocked(resendVerificationV1AuthResendVerificationPost).mockResolvedValue({
      data: undefined,
      error: { detail: "Too many requests." },
      response: new Response(null, { status: 429 }),
    });

    render(<ResendVerificationButton email="ada@example.com" />);
    fireEvent.click(
      screen.getByRole("button", { name: /resend verification email/i }),
    );

    expect(await screen.findByText(/too many requests/i)).toBeInTheDocument();
  });
});
