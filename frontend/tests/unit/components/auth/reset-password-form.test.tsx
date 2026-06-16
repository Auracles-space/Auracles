import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordForm } from "@/components/modules/auth/reset-password-form";
import { resetPassword } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  resetPassword: vi.fn(),
}));

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    vi.mocked(resetPassword).mockReset();
  });

  it("keeps the submit button disabled until token and a long password are set", () => {
    render(<ResetPasswordForm initialToken="reset-token-123" />);

    const submit = screen.getByRole("button", { name: /save password/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "short" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    expect(submit).toBeEnabled();
  });

  it("prefills the token from search params and submits the new password", async () => {
    vi.mocked(resetPassword).mockResolvedValue({
      data: { message: "Password reset." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ResetPasswordForm initialToken="reset-token-123" />);
    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save password/i }));

    expect(await screen.findByText(/password reset/i)).toBeInTheDocument();
    expect(vi.mocked(resetPassword)).toHaveBeenCalledWith({
      body: { new_password: "StrongerPass!234", token: "reset-token-123" },
    });
  });

  it("shows the error detail when the token is rejected", async () => {
    vi.mocked(resetPassword).mockResolvedValue({
      data: undefined,
      error: { detail: "Reset token is invalid or expired." },
      response: new Response(null, { status: 400 }),
    });

    render(<ResetPasswordForm initialToken="expired" />);
    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save password/i }));

    expect(
      await screen.findByText(/reset token is invalid or expired/i),
    ).toBeInTheDocument();
  });
});
