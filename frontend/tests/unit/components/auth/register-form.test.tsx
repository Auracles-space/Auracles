import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/components/modules/auth/register-form";
import { registerUser } from "@/lib/generated/sdk.gen";

const searchParams = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.value,
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  registerUser: vi.fn(),
  resendVerificationV1AuthResendVerificationPost: vi.fn(),
}));

describe("RegisterForm", () => {
  beforeEach(() => {
    vi.mocked(registerUser).mockReset();
    searchParams.value = new URLSearchParams();
  });

  it("keeps the submit button disabled until all fields are valid", () => {
    render(<RegisterForm />);

    const submit = screen.getByRole("button", { name: /create account/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/display name/i), {
      target: { value: "Ada Markets" },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "StrongerPass123!" },
    });
    // No confirm + no role + no terms yet → still disabled.
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/terms of service/i));
    expect(submit).toBeEnabled();

    expect(registerUser).not.toHaveBeenCalled();
  });

  it("keeps submit disabled and warns when the confirm password mismatches", () => {
    render(<RegisterForm />);

    fireEvent.change(screen.getByLabelText(/display name/i), {
      target: { value: "Ada Markets" },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "Mismatched123!" },
    });
    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/terms of service/i));

    expect(
      screen.getByRole("button", { name: /create account/i }),
    ).toBeDisabled();
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it("does not expose admin as a self-assignable registration role", () => {
    render(<RegisterForm />);

    expect(screen.queryByText(/^admin$/i)).not.toBeInTheDocument();
  });

  it("submits valid registration details through the generated client", async () => {
    vi.mocked(registerUser).mockResolvedValue({
      data: { message: "We've sent a verification link to your email. Please check your inbox to activate your account." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<RegisterForm />);

    fireEvent.change(screen.getByLabelText(/display name/i), {
      target: { value: "Ada Markets" },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/terms of service/i));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(registerUser).toHaveBeenCalledWith({
        body: {
          display_name: "Ada Markets",
          email: "ada@example.com",
          password: "StrongerPass123!",
          roles: ["contributor"],
        },
      });
    });
    expect(await screen.findByText(/verification link/i)).toBeInTheDocument();
  });

  it("shows a check-your-inbox panel with a resend option after registering", async () => {
    vi.mocked(registerUser).mockResolvedValue({
      data: { message: "We've sent a verification link to your email." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<RegisterForm />);

    fireEvent.change(screen.getByLabelText(/display name/i), {
      target: { value: "Ada Markets" },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongerPass123!" },
    });
    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/terms of service/i));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByRole("heading", { name: /check your inbox/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /resend verification email/i }),
    ).toBeInTheDocument();
    // The form is replaced by the panel.
    expect(screen.queryByLabelText(/display name/i)).not.toBeInTheDocument();
  });

  it("does not offer Attestor as a self-selectable role", () => {
    render(<RegisterForm />);

    // Attestor is a derived role granted through an organization's active
    // attestor capability; it can never be self-selected at registration.
    expect(screen.queryByLabelText(/attestor/i)).not.toBeInTheDocument();
  });

  it("allows Operator and Contributor to be combined", () => {
    render(<RegisterForm />);

    fireEvent.click(screen.getByLabelText(/operator/i));
    fireEvent.click(screen.getByLabelText(/contributor/i));

    expect(
      (screen.getByLabelText(/operator/i) as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByLabelText(/contributor/i) as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("forwards a safe next path from the URL in the registration body", async () => {
    searchParams.value = new URLSearchParams("next=%2Forganizations%2Finvite%2Fabc");
    vi.mocked(registerUser).mockResolvedValue({
      data: { message: "Check your inbox." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<RegisterForm />);
    fillValidForm();
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(registerUser).toHaveBeenCalledWith({
        body: expect.objectContaining({ next: "/organizations/invite/abc" }),
      });
    });
    // The manual-verification fallback link keeps the intent too.
    expect(screen.getByRole("link", { name: /go to verification/i })).toHaveAttribute(
      "href",
      "/verify-email?next=%2Forganizations%2Finvite%2Fabc",
    );
  });

  it("drops an unsafe next value instead of forwarding it", async () => {
    searchParams.value = new URLSearchParams("next=https%3A%2F%2Fevil.example%2Fphish");
    vi.mocked(registerUser).mockResolvedValue({
      data: { message: "Check your inbox." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<RegisterForm />);
    fillValidForm();
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(registerUser).toHaveBeenCalled());
    const body = vi.mocked(registerUser).mock.calls[0]?.[0]?.body as Record<string, unknown>;
    expect(body).not.toHaveProperty("next");
  });
});

/** Fill every field so the submit button enables. */
function fillValidForm(): void {
  fireEvent.change(screen.getByLabelText(/display name/i), {
    target: { value: "Ada Markets" },
  });
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: "ada@example.com" },
  });
  fireEvent.change(screen.getByLabelText(/^password/i), {
    target: { value: "StrongerPass123!" },
  });
  fireEvent.change(screen.getByLabelText(/confirm password/i), {
    target: { value: "StrongerPass123!" },
  });
  fireEvent.click(screen.getByLabelText(/contributor/i));
  fireEvent.click(screen.getByLabelText(/terms of service/i));
}
