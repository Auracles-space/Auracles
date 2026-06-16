import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TotpSetupPanel } from "@/components/modules/auth/totp-setup-panel";
import { setupTotp, verifyTotp } from "@/lib/generated/sdk.gen";

vi.mock("next/image", () => ({
  default: (props: { alt: string }) => <img alt={props.alt} />,
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  setupTotp: vi.fn(),
  verifyTotp: vi.fn(),
}));

describe("TotpSetupPanel", () => {
  beforeEach(() => {
    vi.mocked(setupTotp).mockReset();
    vi.mocked(verifyTotp).mockReset();
  });

  it("starts enrollment and renders the QR payload and backup codes", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: {
        backup_codes: ["aaaa-1111", "bbbb-2222"],
        provisioning_uri: "otpauth://totp/Auracles:ada",
        qr_png_base64: "QRDATA",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    expect(
      await screen.findByText(/otpauth:\/\/totp\/auracles:ada/i),
    ).toBeInTheDocument();
    expect(screen.getByText("aaaa-1111")).toBeInTheDocument();
    expect(screen.getByText("bbbb-2222")).toBeInTheDocument();
  });

  it("keeps verify-and-enable disabled until a 6-digit code is entered", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: {
        backup_codes: ["aaaa-1111"],
        provisioning_uri: "otpauth://totp/Auracles:ada",
        qr_png_base64: "QRDATA",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    const verify = await screen.findByRole("button", {
      name: /verify and enable/i,
    });
    expect(verify).toBeDisabled();

    fireEvent.change(await screen.findByLabelText(/authenticator code/i), {
      target: { value: "123" },
    });
    expect(verify).toBeDisabled();

    fireEvent.change(await screen.findByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    expect(verify).toBeEnabled();
  });

  it("enables 2FA after verifying the first code", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: {
        backup_codes: ["aaaa-1111"],
        provisioning_uri: "otpauth://totp/Auracles:ada",
        qr_png_base64: "QRDATA",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(verifyTotp).mockResolvedValue({
      data: { message: "ok" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));
    fireEvent.change(await screen.findByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify and enable/i }));

    expect(
      await screen.findByText(/two-factor authentication is enabled/i),
    ).toBeInTheDocument();

    // Form resets after success: QR/verify controls collapse.
    expect(
      screen.queryByRole("button", { name: /verify and enable/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /start 2fa setup/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/authenticator code/i),
    ).not.toBeInTheDocument();
  });

  it("copies backup codes to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    vi.mocked(setupTotp).mockResolvedValue({
      data: {
        backup_codes: ["aaaa-1111", "bbbb-2222"],
        provisioning_uri: "otpauth://totp/Auracles:ada",
        qr_png_base64: "QRDATA",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    const copy = await screen.findByRole("button", { name: /copy codes/i });
    fireEvent.click(copy);

    expect(writeText).toHaveBeenCalledWith("aaaa-1111\nbbbb-2222");
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("surfaces a setup error from the API", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: undefined,
      error: { detail: "2FA already enabled." },
      response: new Response(null, { status: 409 }),
    });

    render(<TotpSetupPanel />);
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    expect(await screen.findByText(/2fa already enabled/i)).toBeInTheDocument();
  });
});
