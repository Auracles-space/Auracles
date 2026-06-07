import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/components/modules/auth/register-form";
import { registerUser } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  registerUser: vi.fn(),
}));

describe("RegisterForm", () => {
  beforeEach(() => {
    vi.mocked(registerUser).mockReset();
  });

  it("requires at least one role before submitting registration", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByText(/select at least one role/i),
    ).toBeInTheDocument();
    expect(registerUser).not.toHaveBeenCalled();
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
});
