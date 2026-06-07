import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";
import { requestEmailChange } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  deactivateAccount: vi.fn(),
  requestEmailChange: vi.fn(),
}));

describe("AccountSettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(requestEmailChange).mockReset();
  });

  it("requires a 2FA code before requesting an email change", async () => {
    render(<AccountSettingsPanel />);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    expect(await screen.findByText(/enter a 2fa code/i)).toBeInTheDocument();
    expect(requestEmailChange).not.toHaveBeenCalled();
  });

  it("submits an email-change request through the generated client", async () => {
    vi.mocked(requestEmailChange).mockResolvedValue({
      data: { message: "Email change verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.change(screen.getByLabelText(/2fa code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    await waitFor(() => {
      expect(requestEmailChange).toHaveBeenCalledWith({
        body: { new_email: "next@auracles.space", totp_code: "123456" },
        headers: { Authorization: "Bearer access-token" },
      });
    });
  });
});
