import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VerifyEmailForm } from "@/components/modules/auth/verify-email-form";
import { verifyEmail } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  verifyEmail: vi.fn(),
}));

describe("VerifyEmailForm", () => {
  beforeEach(() => {
    vi.mocked(verifyEmail).mockReset();
  });

  it("keeps the submit button disabled until a token is present", () => {
    render(<VerifyEmailForm />);

    const submit = screen.getByRole("button", { name: /verify email/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/verification token/i), {
      target: { value: "verify-token-9" },
    });
    expect(submit).toBeEnabled();
  });

  it("verifies the email with the prefilled token", async () => {
    vi.mocked(verifyEmail).mockResolvedValue({
      data: { message: "Email verified." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<VerifyEmailForm initialToken="verify-token-9" />);
    fireEvent.click(screen.getByRole("button", { name: /verify email/i }));

    expect(await screen.findByText(/email verified/i)).toBeInTheDocument();
    expect(vi.mocked(verifyEmail)).toHaveBeenCalledWith({
      body: { token: "verify-token-9" },
    });
  });

  it("surfaces the error detail for an invalid token", async () => {
    vi.mocked(verifyEmail).mockResolvedValue({
      data: undefined,
      error: { detail: "Verification token is invalid." },
      response: new Response(null, { status: 400 }),
    });

    render(<VerifyEmailForm initialToken="bad" />);
    fireEvent.click(screen.getByRole("button", { name: /verify email/i }));

    expect(
      await screen.findByText(/verification token is invalid/i),
    ).toBeInTheDocument();
  });
});
