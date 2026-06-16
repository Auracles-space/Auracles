import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm } from "@/components/modules/auth/forgot-password-form";
import { forgotPassword } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  forgotPassword: vi.fn(),
}));

describe("ForgotPasswordForm", () => {
  beforeEach(() => {
    vi.mocked(forgotPassword).mockReset();
  });

  it("keeps the submit button disabled until a valid email is entered", () => {
    render(<ForgotPasswordForm />);

    const submit = screen.getByRole("button", { name: /send reset link/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "not-an-email" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    expect(submit).toBeEnabled();
  });

  it("shows the no-enumeration success copy on a successful request", async () => {
    vi.mocked(forgotPassword).mockResolvedValue({
      data: { message: "If email is valid, reset link sent." },
      error: undefined,
      response: new Response(null, { status: 202 }),
    });

    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(
      await screen.findByText(/if email is valid, reset link sent/i),
    ).toBeInTheDocument();
    expect(vi.mocked(forgotPassword)).toHaveBeenCalledWith({
      body: { email: "ada@example.com" },
    });
  });

  it("surfaces a generated-client error detail", async () => {
    vi.mocked(forgotPassword).mockResolvedValue({
      data: undefined,
      error: { detail: "Too many reset requests." },
      response: new Response(null, { status: 429 }),
    });

    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(
      await screen.findByText(/too many reset requests/i),
    ).toBeInTheDocument();
  });
});
