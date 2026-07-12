import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KycUpload } from "@/components/modules/auth/kyc-upload";
import {
  getKycStatusV1SettingsKycGet,
  startIdentityVerificationV1SettingsKycSessionPost,
  syncKycFromReturnV1SettingsKycSyncPost,
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
  syncKycFromReturnV1SettingsKycSyncPost: vi.fn(),
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
    vi.mocked(syncKycFromReturnV1SettingsKycSyncPost).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "unverified", documents: [] }),
    );
    // Default: no inquiry-id on the URL (fresh visit, not a hosted-flow return).
    window.history.replaceState({}, "", "/settings/kyc");
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

  it("syncs the verdict from Persona when returning with an inquiry id", async () => {
    // The hosted flow redirects back with ?inquiry-id=... The panel must read
    // the authoritative verdict server-to-server instead of showing a stale
    // pending state while waiting for the webhook.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        search: "?inquiry-id=inq_9",
        pathname: "/settings/kyc",
        assign: vi.fn(),
      },
    });
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "pending", documents: [] }),
    );
    vi.mocked(syncKycFromReturnV1SettingsKycSyncPost).mockResolvedValue(
      ok({ kyc_status: "verified", documents: [] }),
    );

    render(<KycUpload />);

    await waitFor(() => {
      expect(syncKycFromReturnV1SettingsKycSyncPost).toHaveBeenCalled();
    });
    expect(
      vi.mocked(syncKycFromReturnV1SettingsKycSyncPost).mock.calls[0][0]?.body,
    ).toMatchObject({ inquiry_id: "inq_9" });
    await waitFor(() => {
      expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    });
  });

  it("lets a stuck pending user restart the Persona flow", async () => {
    // A user who abandoned or failed the hosted flow is left pending until a
    // webhook that may never arrive. The panel must still offer a restart so
    // they are not locked out. Backend allows pending -> new inquiry.
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign },
    });
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "pending", documents: [] }),
    );
    vi.mocked(startIdentityVerificationV1SettingsKycSessionPost).mockResolvedValue({
      data: { hosted_url: "https://withpersona.com/verify?inquiry-id=inq_2", inquiry_id: "inq_2" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.getByText(/verification pending/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /restart verification/i }));

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        "https://withpersona.com/verify?inquiry-id=inq_2",
      );
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
