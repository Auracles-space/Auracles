import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordForm } from "@/components/modules/auth/reset-password-form";
import { clearBrowserSessionHintCookie } from "@/lib/auth/current-user-session";
import { clearAuthToken } from "@/lib/auth/token-store";
import { resetPassword } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  clearBrowserSessionHintCookie: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  clearAuthToken: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  resetPassword: vi.fn(),
}));

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    vi.mocked(resetPassword).mockReset();
    vi.mocked(clearBrowserSessionHintCookie).mockReset();
    vi.mocked(clearAuthToken).mockReset();
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
    // Long password but confirm still empty → mismatch keeps it disabled.
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass!234" },
    });
    expect(submit).toBeEnabled();
  });

  it("keeps the submit disabled when the confirm password does not match", () => {
    render(<ResetPasswordForm initialToken="reset-token-123" />);

    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "DifferentPass!234" },
    });

    expect(screen.getByRole("button", { name: /save password/i })).toBeDisabled();
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it("submits the new password and routes to login on success", async () => {
    vi.mocked(resetPassword).mockResolvedValue({
      data: { message: "Password reset." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    const onReset = vi.fn();
    render(<ResetPasswordForm initialToken="reset-token-123" onReset={onReset} />);
    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save password/i }));

    expect(await screen.findByText(/password reset/i)).toBeInTheDocument();
    expect(vi.mocked(resetPassword)).toHaveBeenCalledWith({
      body: { new_password: "StrongerPass!234", token: "reset-token-123" },
    });
    expect(onReset).toHaveBeenCalledWith("/login");
  });

  it("clears the stale session hint and access token on success so a still-authenticated user lands on login", async () => {
    vi.mocked(resetPassword).mockResolvedValue({
      data: { message: "Password reset." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    const onReset = vi.fn();
    render(<ResetPasswordForm initialToken="reset-token-123" onReset={onReset} />);
    fireEvent.change(screen.getByLabelText(/new password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save password/i }));

    await screen.findByText(/password reset/i);
    // Backend revokes the refresh session; the browser must drop its readable
    // session hint too, or middleware routes /login back into the app.
    expect(vi.mocked(clearBrowserSessionHintCookie)).toHaveBeenCalledOnce();
    expect(vi.mocked(clearAuthToken)).toHaveBeenCalledOnce();
    expect(onReset).toHaveBeenCalledWith("/login");
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
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass!234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save password/i }));

    expect(
      await screen.findByText(/reset token is invalid or expired/i),
    ).toBeInTheDocument();
  });
});
