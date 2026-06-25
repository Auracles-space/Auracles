import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KycUpload } from "@/components/modules/auth/kyc-upload";
import {
  getKycStatusV1SettingsKycGet,
  startIdentityVerificationV1SettingsKycSessionPost,
} from "@/lib/generated/sdk.gen";
import type { GetKycStatusV1SettingsKycGetResponse } from "@/lib/generated/types.gen";

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
  getKycStatusV1SettingsKycGet: vi.fn(),
  startIdentityVerificationV1SettingsKycSessionPost: vi.fn(),
}));

describe("KycUpload", () => {
  function ok(data: GetKycStatusV1SettingsKycGetResponse) {
    return {
      data,
      error: undefined,
      response: new Response(null, { status: 200 }),
    };
  }

  beforeEach(() => {
    vi.mocked(startIdentityVerificationV1SettingsKycSessionPost).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "unverified", documents: [] }),
    );
  });

  it("launches the Persona hosted flow when the user starts verification", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign },
    });
    vi.mocked(startIdentityVerificationV1SettingsKycSessionPost).mockResolvedValue({
      data: { hosted_url: "https://withpersona.com/verify?inquiry-id=inq_1", inquiry_id: "inq_1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /verify identity/i }));

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        "https://withpersona.com/verify?inquiry-id=inq_1",
      );
    });
  });

  it("refetches the KYC status when the window regains focus", async () => {
    // Pending on mount, verified by the time the user tabs back — the webhook
    // landed in the meantime. Focus must re-read without a manual refresh.
    vi.mocked(getKycStatusV1SettingsKycGet)
      .mockResolvedValueOnce(ok({ kyc_status: "pending", documents: [] }))
      .mockResolvedValue(ok({ kyc_status: "verified", documents: [] }));

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.getByText(/verification pending/i)).toBeInTheDocument();
    });

    fireEvent.focus(window);

    await waitFor(() => {
      expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    });
  });

  it("shows the verified state and hides the CTA when KYC is verified", async () => {
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "verified", documents: [] }),
    );

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /verify identity/i }),
    ).not.toBeInTheDocument();
  });
});
