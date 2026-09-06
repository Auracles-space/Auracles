/**
 * Unit coverage for the admin user directory panel.
 *
 * Verifies directory rendering plus the suspend/unsuspend mutation workflow
 * used by the admin account-controls page.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminUserDirectoryPanel } from "@/components/modules/admin/admin-user-directory-panel";
import {
  listAdminUsersV1AdminUsersGet,
  listUserKycDocumentsV1AdminUsersUserIdKycDocumentsGet,
  reviewKycV1AdminUsersUserIdKycPatch,
  suspendUserV1AdminUsersUserIdSuspendPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  downloadUserKycDocumentV1AdminUsersUserIdKycDocumentsDocumentIdDownloadGet:
    vi.fn(),
  listAdminUsersV1AdminUsersGet: vi.fn(),
  // The KYC review form embeds the submitted-document list, which loads on
  // open; without this the panel's own tests fail on an unmocked export.
  listUserKycDocumentsV1AdminUsersUserIdKycDocumentsGet: vi.fn(),
  reviewKycV1AdminUsersUserIdKycPatch: vi.fn(),
  suspendUserV1AdminUsersUserIdSuspendPost: vi.fn(),
  unsuspendUserV1AdminUsersUserIdUnsuspendPost: vi.fn(),
}));

describe("AdminUserDirectoryPanel", () => {
  beforeEach(() => {
    vi.mocked(listAdminUsersV1AdminUsersGet).mockReset();
    vi.mocked(suspendUserV1AdminUsersUserIdSuspendPost).mockReset();
    vi.mocked(
      listUserKycDocumentsV1AdminUsersUserIdKycDocumentsGet,
    ).mockResolvedValue({
      data: { documents: [], user_id: "user-1" },
      error: undefined,
      request: new Request("http://127.0.0.1:8000"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(listAdminUsersV1AdminUsersGet).mockResolvedValue({
      data: {
        items: [
          {
            created_at: "2026-06-10T09:00:00Z",
            display_name: "Ada Contributor",
            email: "ada@example.com",
            roles: ["contributor", "developer"],
            suspended: false,
            suspended_at: null,
            user_id: "user-1",
            kyc_status: "pending",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(suspendUserV1AdminUsersUserIdSuspendPost).mockResolvedValue({
      data: {
        suspended: true,
        suspended_at: "2026-06-12T15:00:00Z",
        suspended_by: "admin-1",
        suspension_reason: "Fraud review",
        user_id: "user-1",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("renders directory rows and suspends a selected user with reason and TOTP", async () => {
    render(<AdminUserDirectoryPanel />);

    expect(await screen.findByRole("heading", { name: /user controls/i })).toBeInTheDocument();
    const userCard = screen.getByRole("article", { name: /ada contributor/i });
    expect(within(userCard).getByText("ada@example.com")).toBeInTheDocument();

    fireEvent.click(within(userCard).getByRole("button", { name: /suspend/i }));
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Fraud review" },
    });
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm suspension/i }));

    await waitFor(() => {
      expect(suspendUserV1AdminUsersUserIdSuspendPost).toHaveBeenCalledWith({
        body: {
          reason: "Fraud review",
          totp_code: "123456",
        },
        headers: { Authorization: "Bearer admin-token" },
        path: { user_id: "user-1" },
      });
    });

    expect(await within(userCard).findByText(/suspended/i)).toBeInTheDocument();
  });

  it("approves a pending KYC submission with notes", async () => {
    vi.mocked(reviewKycV1AdminUsersUserIdKycPatch).mockResolvedValue({
      data: {
        user_id: "user-1",
        kyc_status: "verified",
        document_status: "approved",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AdminUserDirectoryPanel />);
    const userCard = await screen.findByRole("article", {
      name: /ada contributor/i,
    });

    fireEvent.click(within(userCard).getByRole("button", { name: /review kyc/i }));
    fireEvent.change(within(userCard).getByLabelText(/notes/i), {
      target: { value: "Docs verified" },
    });
    // The override unlocks payouts, so it is TOTP-gated: the action stays
    // disabled until a code is entered.
    fireEvent.change(within(userCard).getByLabelText(/authenticator code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(within(userCard).getByRole("button", { name: /approve kyc/i }));

    await waitFor(() => {
      expect(reviewKycV1AdminUsersUserIdKycPatch).toHaveBeenCalledWith({
        body: {
          status: "verified",
          notes: "Docs verified",
          totp_code: "123456",
        },
        headers: { Authorization: "Bearer admin-token" },
        path: { user_id: "user-1" },
      });
    });

    expect(
      await within(userCard).findByText(/KYC: verified/i),
    ).toBeInTheDocument();
  });
});
