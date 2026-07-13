/**
 * Unit coverage for the dedicated consent settings panel.
 *
 * Verifies current-version consent state, append-only history, and the
 * re-accept action used by the consent-required redirect flow.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConsentSettingsPanel } from "@/components/modules/settings/consent-settings-panel";
import { ToastProvider } from "@/components/ui/toast";
import {
  acceptCurrentConsentV1GdprConsentPost,
  listConsentHistoryV1GdprConsentGet,
} from "@/lib/generated/sdk.gen";

/** Render the panel beneath the toast provider its accept action depends on. */
function renderPanel(): void {
  render(
    <ToastProvider>
      <ConsentSettingsPanel />
    </ToastProvider>,
  );
}

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptCurrentConsentV1GdprConsentPost: vi.fn(),
  listConsentHistoryV1GdprConsentGet: vi.fn(),
}));

describe("ConsentSettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(acceptCurrentConsentV1GdprConsentPost).mockReset();
    vi.mocked(listConsentHistoryV1GdprConsentGet).mockReset();
    vi.mocked(listConsentHistoryV1GdprConsentGet).mockResolvedValue({
      data: {
        current_versions: {
          privacy_policy: "2.0",
          terms_of_service: "2.0",
        },
        items: [
          {
            accepted_at: "2026-06-01T08:00:00Z",
            document_type: "terms_of_service",
            id: "consent-1",
            version: "1.0",
          },
          {
            accepted_at: "2026-06-01T08:00:00Z",
            document_type: "privacy_policy",
            id: "consent-2",
            version: "1.0",
          },
        ],
        missing_documents: ["terms_of_service", "privacy_policy"],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("loads missing current consent versions and the consent history", async () => {
    renderPanel();

    const consentSection = await screen.findByRole("region", {
      name: /legal consent/i,
    });

    expect(
      await within(consentSection).findByText(/new legal versions require your acceptance/i),
    ).toBeInTheDocument();
    expect(
      within(consentSection).getAllByText(/terms of service/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(consentSection).getAllByText(/privacy policy/i).length,
    ).toBeGreaterThan(0);
    expect(within(consentSection).getAllByText(/version 1\.0/i).length).toBe(2);
  });

  it("accepts the current consent versions and clears the missing state", async () => {
    vi.mocked(acceptCurrentConsentV1GdprConsentPost).mockResolvedValue({
      data: {
        current_versions: {
          privacy_policy: "2.0",
          terms_of_service: "2.0",
        },
        items: [
          {
            accepted_at: "2026-06-12T10:00:00Z",
            document_type: "terms_of_service",
            id: "consent-3",
            version: "2.0",
          },
          {
            accepted_at: "2026-06-12T10:00:00Z",
            document_type: "privacy_policy",
            id: "consent-4",
            version: "2.0",
          },
        ],
        missing_documents: [],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    renderPanel();

    const consentSection = await screen.findByRole("region", {
      name: /legal consent/i,
    });

    fireEvent.click(
      within(consentSection).getByRole("button", { name: /accept current versions/i }),
    );

    await waitFor(() => {
      expect(acceptCurrentConsentV1GdprConsentPost).toHaveBeenCalledWith({
        body: {
          accept_privacy_policy: true,
          accept_terms: true,
        },
        headers: { Authorization: "Bearer access-token" },
      });
    });

    // The confirmation now surfaces in a toast (the live region) rather than a
    // banner inside the section.
    const toastRegion = await screen.findByRole("status");
    expect(
      within(toastRegion).getByText(/you are up to date on legal consent/i),
    ).toBeInTheDocument();
  });
});
