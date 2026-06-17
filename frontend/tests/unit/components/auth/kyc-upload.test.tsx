import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KycUpload } from "@/components/modules/auth/kyc-upload";
import {
  getKycStatusV1SettingsKycGet,
  requestKycUploadUrl,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  ensureBrowserAccessToken: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  requestKycUploadUrl: vi.fn(),
  submitKycUpload: vi.fn(),
  getKycStatusV1SettingsKycGet: vi.fn(),
}));

describe("KycUpload", () => {
  beforeEach(() => {
    vi.mocked(requestKycUploadUrl).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue({
      data: { kyc_status: "unverified", documents: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as any);
  });

  it("keeps the submit disabled until a document file is selected", async () => {
    const { container } = render(<KycUpload />);

    // Wait for initial load to finish
    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    const submit = screen.getByRole("button", { name: /submit document/i });
    expect(submit).toBeDisabled();

    const fileInput = container.querySelector(
      "#doc-upload",
    ) as HTMLInputElement;
    const file = new File(["id-bytes"], "passport.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(submit).toBeEnabled();
  });

  it("does not request an upload URL while no file is selected", async () => {
    render(<KycUpload />);

    // Wait for initial load to finish
    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /submit document/i }));

    expect(requestKycUploadUrl).not.toHaveBeenCalled();
  });

  it("refetches the KYC status when the window regains focus", async () => {
    // Pending on mount, verified by the time the user tabs back — the admin
    // approved in the meantime. Focus must re-read without a manual refresh.
    vi.mocked(getKycStatusV1SettingsKycGet)
      .mockResolvedValueOnce({
        data: { kyc_status: "pending", documents: [] },
        error: undefined,
        response: new Response(null, { status: 200 }),
      } as any)
      .mockResolvedValue({
        data: { kyc_status: "verified", documents: [] },
        error: undefined,
        response: new Response(null, { status: 200 }),
      } as any);

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.getByText(/verification pending/i)).toBeInTheDocument();
    });

    fireEvent.focus(window);

    await waitFor(() => {
      expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    });
  });

  it("shows the verified state and hides the form when KYC is verified", async () => {
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue({
      data: { kyc_status: "verified", documents: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as any);

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /submit document/i }),
    ).not.toBeInTheDocument();
  });
});
