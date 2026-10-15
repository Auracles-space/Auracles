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
  setUserProjectCapV1AdminUsersUserIdProjectCapPatch,
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
  setUserProjectCapV1AdminUsersUserIdProjectCapPatch: vi.fn(),
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
            max_active_projects: null,
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

  it("renders directory rows and suspends a selected user with a reason", async () => {
    render(<AdminUserDirectoryPanel />);

    expect(await screen.findByRole("heading", { name: /user controls/i })).toBeInTheDocument();
    const userCard = screen.getByRole("article", { name: /ada contributor/i });
    expect(within(userCard).getByText("ada@example.com")).toBeInTheDocument();

    fireEvent.click(within(userCard).getByRole("button", { name: /suspend/i }));
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Fraud review" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm suspension/i }));

    await waitFor(() => {
      expect(suspendUserV1AdminUsersUserIdSuspendPost).toHaveBeenCalledWith({
        body: {
          reason: "Fraud review",
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
    // The override unlocks payouts; the API requires a step-up window and the
    // global prompt handles it, so the form itself collects no code.
    fireEvent.click(within(userCard).getByRole("button", { name: /approve kyc/i }));

    await waitFor(() => {
      expect(reviewKycV1AdminUsersUserIdKycPatch).toHaveBeenCalledWith({
        body: {
          status: "verified",
          notes: "Docs verified",
        },
        headers: { Authorization: "Bearer admin-token" },
        path: { user_id: "user-1" },
      });
    });

    expect(
      await within(userCard).findByText(/KYC: verified/i),
    ).toBeInTheDocument();
  });
  it("raises one Operator's active-Project ceiling with a reason", async () => {
    vi.mocked(
      setUserProjectCapV1AdminUsersUserIdProjectCapPatch,
    ).mockResolvedValue({
      data: {
        user_id: "user-1",
        max_active_projects: 25,
        default_max_active_projects: 5,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AdminUserDirectoryPanel />);
    const userCard = await screen.findByRole("article", {
      name: /ada contributor/i,
    });

    fireEvent.click(
      within(userCard).getByRole("button", { name: /project limit/i }),
    );
    fireEvent.change(within(userCard).getByLabelText(/concurrent active/i), {
      target: { value: "25" },
    });
    fireEvent.change(within(userCard).getByLabelText(/why this account/i), {
      target: { value: "Pilot operator running the launch cohort." },
    });
    fireEvent.click(
      within(userCard).getByRole("button", { name: /save limit/i }),
    );

    await waitFor(() => {
      expect(
        setUserProjectCapV1AdminUsersUserIdProjectCapPatch,
      ).toHaveBeenCalledWith({
        body: {
          max_active_projects: 25,
          reason: "Pilot operator running the launch cohort.",
        },
        headers: { Authorization: "Bearer admin-token" },
        path: { user_id: "user-1" },
      });
    });

    // The exception is visible on the row afterwards, so an admin scanning the
    // directory can see who is not on the default.
    expect(await within(userCard).findByText(/25 projects/i)).toBeInTheDocument();
  });

  it("accepts a four-figure ceiling and refuses an implausible one", async () => {
    // The form's own bound was 500, so Save stayed disabled on a legitimate
    // 1000 and the admin had no way through and no message saying why. The
    // guard is kept but moved to where nobody lands on purpose, and it has to
    // match AdminProjectCapRequest or the form refuses what the API allows.
    const { listAdminUsersV1AdminUsersGet } = await import(
      "@/lib/generated/sdk.gen"
    );
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
            max_active_projects: null,
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<AdminUserDirectoryPanel />);
    const userCard = await screen.findByRole("article", {
      name: /ada contributor/i,
    });
    fireEvent.click(
      within(userCard).getByRole("button", { name: /project limit/i }),
    );
    fireEvent.change(within(userCard).getByLabelText(/why this account/i), {
      target: { value: "High-volume Operator." },
    });

    fireEvent.change(within(userCard).getByLabelText(/concurrent active/i), {
      target: { value: "1000" },
    });
    expect(
      within(userCard).getByRole("button", { name: /save limit/i }),
    ).toBeEnabled();

    fireEvent.change(within(userCard).getByLabelText(/concurrent active/i), {
      target: { value: "10001" },
    });
    expect(
      within(userCard).getByRole("button", { name: /save limit/i }),
    ).toBeDisabled();
  });

  it("clears the ceiling by sending null rather than the default number", async () => {
    // Writing 5 would pin the account to today's value of BR-PROJ-004; null
    // returns it to following the rule.
    vi.mocked(listAdminUsersV1AdminUsersGet).mockResolvedValue({
      data: {
        items: [
          {
            created_at: "2026-06-10T09:00:00Z",
            display_name: "Ada Contributor",
            email: "ada@example.com",
            roles: ["contributor"],
            suspended: false,
            suspended_at: null,
            user_id: "user-1",
            kyc_status: "verified",
            max_active_projects: 25,
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(
      setUserProjectCapV1AdminUsersUserIdProjectCapPatch,
    ).mockResolvedValue({
      data: {
        user_id: "user-1",
        max_active_projects: null,
        default_max_active_projects: 5,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AdminUserDirectoryPanel />);
    const userCard = await screen.findByRole("article", {
      name: /ada contributor/i,
    });

    fireEvent.click(
      within(userCard).getByRole("button", { name: /project limit/i }),
    );
    fireEvent.change(within(userCard).getByLabelText(/why this account/i), {
      target: { value: "Pilot cohort finished." },
    });
    fireEvent.click(
      within(userCard).getByRole("button", { name: /remove exception/i }),
    );

    await waitFor(() => {
      expect(
        setUserProjectCapV1AdminUsersUserIdProjectCapPatch,
      ).toHaveBeenCalledWith({
        body: {
          max_active_projects: null,
          reason: "Pilot cohort finished.",
        },
        headers: { Authorization: "Bearer admin-token" },
        path: { user_id: "user-1" },
      });
    });
  });
});
