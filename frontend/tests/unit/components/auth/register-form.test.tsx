import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/components/modules/auth/register-form";
import { registerUser } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  registerUser: vi.fn(),
}));

describe("RegisterForm", () => {
  beforeEach(() => {
    vi.mocked(registerUser).mockReset();
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
    // No role + no terms yet → still disabled.
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/terms of service/i));
    expect(submit).toBeEnabled();

    expect(registerUser).not.toHaveBeenCalled();
  });

  it("does not expose admin as a self-assignable registration role", () => {
    render(<RegisterForm />);

    expect(screen.queryByText(/^admin$/i)).not.toBeInTheDocument();
  });

  it("submits valid registration details through the generated client", async () => {
    vi.mocked(registerUser).mockResolvedValue({
      data: { message: "If email is new, verification sent." },
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
    expect(await screen.findByText(/verification sent/i)).toBeInTheDocument();
  });

  it("clears other roles when Attestor is selected", () => {
    render(<RegisterForm />);

    fireEvent.click(screen.getByLabelText(/operator/i));
    fireEvent.click(screen.getByLabelText(/contributor/i));
    fireEvent.click(screen.getByLabelText(/attestor/i));

    expect(
      (screen.getByLabelText(/attestor/i) as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByLabelText(/operator/i) as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      (screen.getByLabelText(/contributor/i) as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("clears Attestor when Operator or Contributor is selected", () => {
    render(<RegisterForm />);

    fireEvent.click(screen.getByLabelText(/attestor/i));
    fireEvent.click(screen.getByLabelText(/operator/i));

    expect(
      (screen.getByLabelText(/attestor/i) as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      (screen.getByLabelText(/operator/i) as HTMLInputElement).checked,
    ).toBe(true);
  });
});
