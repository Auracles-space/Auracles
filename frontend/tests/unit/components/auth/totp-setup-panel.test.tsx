import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TotpSetupPanel } from "@/components/modules/auth/totp-setup-panel";
import {
  disableTotp,
  regenerateBackupCodes,
  setupTotp,
  totpStatus,
  verifyTotp,
} from "@/lib/generated/sdk.gen";
import type { TotpStatusResponse } from "@/lib/generated/types.gen";

vi.mock("next/image", () => ({
  default: (props: { alt: string }) => <span aria-label={props.alt} />,
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
  disableTotp: vi.fn(),
  regenerateBackupCodes: vi.fn(),
  totpStatus: vi.fn(),
}));

const SETUP_BODY = {
  backup_codes: ["aaaa-1111", "bbbb-2222"],
  provisioning_uri: "otpauth://totp/Auracles:ada",
  qr_png_base64: "QRDATA",
};

function mockStatus(totp_enabled: boolean, backup_codes_remaining = 0) {
  vi.mocked(totpStatus).mockResolvedValue({
    data: { totp_enabled, backup_codes_remaining },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } satisfies {
    data: TotpStatusResponse;
    error: undefined;
    response: Response;
  });
}

async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
  });
}

describe("TotpSetupPanel", () => {
  beforeEach(() => {
    vi.mocked(setupTotp).mockReset();
    vi.mocked(verifyTotp).mockReset();
    vi.mocked(disableTotp).mockReset();
    vi.mocked(regenerateBackupCodes).mockReset();
    vi.mocked(totpStatus).mockReset();
    mockStatus(false);
  });

  it("starts enrollment and renders the QR payload and backup codes", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: SETUP_BODY,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    expect(
      await screen.findByText(/otpauth:\/\/totp\/auracles:ada/i),
    ).toBeInTheDocument();
    expect(screen.getByText("aaaa-1111")).toBeInTheDocument();
    expect(screen.getByText("bbbb-2222")).toBeInTheDocument();
  });

  it("keeps verify-and-enable disabled until a 6-digit code is entered", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: SETUP_BODY,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
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

  it("enables 2FA after verifying the first code and shows the enabled panel", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: SETUP_BODY,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(verifyTotp).mockResolvedValue({
      data: { message: "ok" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));
    fireEvent.change(await screen.findByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify and enable/i }));

    expect(
      await screen.findByText(/two-factor authentication is enabled/i),
    ).toBeInTheDocument();
    // Enrollment form collapses after success.
    expect(
      screen.queryByRole("button", { name: /verify and enable/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/authenticator code/i),
    ).not.toBeInTheDocument();
  });

  it("copies backup codes to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    vi.mocked(setupTotp).mockResolvedValue({
      data: SETUP_BODY,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    const copy = await screen.findByRole("button", { name: /copy codes/i });
    fireEvent.click(copy);

    expect(writeText).toHaveBeenCalledWith("aaaa-1111\nbbbb-2222");
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("shows enabled state with remaining backup-code count", async () => {
    mockStatus(true, 7);

    render(<TotpSetupPanel />);
    await waitForLoaded();

    expect(
      await screen.findByText(/two-factor authentication is enabled/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/7 backup codes remaining/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set up on a new device/i }),
    ).toBeInTheDocument();
  });

  it("re-enrolls on a new device: disable then fresh QR", async () => {
    mockStatus(true, 3);
    vi.mocked(disableTotp).mockResolvedValue({
      data: { totp_enabled: false },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(setupTotp).mockResolvedValue({
      data: SETUP_BODY,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(
      await screen.findByRole("button", { name: /set up on a new device/i }),
    );
    fireEvent.change(
      await screen.findByLabelText(/authenticator or backup code/i),
      { target: { value: "aaaa-1111" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /confirm and re-enroll/i }),
    );

    expect(
      await screen.findByText(/otpauth:\/\/totp\/auracles:ada/i),
    ).toBeInTheDocument();
    expect(disableTotp).toHaveBeenCalledWith(
      expect.objectContaining({ body: { code: "aaaa-1111" } }),
    );
    expect(setupTotp).toHaveBeenCalled();
  });

  it("regenerates backup codes and shows the new set", async () => {
    mockStatus(true, 1);
    vi.mocked(regenerateBackupCodes).mockResolvedValue({
      data: { backup_codes: ["cccc-3333", "dddd-4444"] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(
      await screen.findByRole("button", { name: /regenerate backup codes/i }),
    );
    fireEvent.change(
      await screen.findByLabelText(/authenticator or backup code/i),
      { target: { value: "123456" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /confirm and regenerate/i }),
    );

    expect(await screen.findByText("cccc-3333")).toBeInTheDocument();
    expect(screen.getByText("dddd-4444")).toBeInTheDocument();
    expect(regenerateBackupCodes).toHaveBeenCalledWith(
      expect.objectContaining({ body: { code: "123456" } }),
    );
  });

  it("surfaces a setup error from the API", async () => {
    vi.mocked(setupTotp).mockResolvedValue({
      data: undefined,
      error: { detail: "2FA already enabled." },
      response: new Response(null, { status: 409 }),
    });

    render(<TotpSetupPanel />);
    await waitForLoaded();
    fireEvent.click(screen.getByRole("button", { name: /start 2fa setup/i }));

    expect(await screen.findByText(/2fa already enabled/i)).toBeInTheDocument();
  });
});
