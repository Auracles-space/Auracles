import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperatorLibrary } from "@/components/modules/library/operator-library";
import {
  downloadLicensedArtifact,
  getExploreFrameworkDetail,
  listOperatorLibrary,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  downloadLicensedArtifact: vi.fn(),
  getExploreFrameworkDetail: vi.fn(),
  listOperatorLibrary: vi.fn(),
}));

// The review panel makes its own API calls; isolate it from this unit.
vi.mock("@/components/modules/library/framework-review-panel", () => ({
  FrameworkReviewPanel: () => null,
}));

function libraryItem() {
  return {
    license_id: "lic-1",
    framework_id: "fw-1",
    license_type: "single_user",
    title: "Board Risk Operating System",
    version_at_grant: "1.0.0",
    current_version: "1.1.0",
    price: "499.00",
    currency: "USD",
    status: "active",
    source: "purchase",
    seats_used: 1,
    seats_total: 1,
    expires_at: null,
  };
}

describe("OperatorLibrary", () => {
  beforeEach(() => {
    vi.mocked(listOperatorLibrary).mockReset();
    vi.mocked(getExploreFrameworkDetail).mockReset();
    vi.mocked(downloadLicensedArtifact).mockReset();
  });

  it("shows the empty state when no licenses exist", async () => {
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: { items: [], page: 1, page_size: 25, total: 0 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<OperatorLibrary />);

    expect(
      await screen.findByText(/no licensed frameworks yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces a library load error", async () => {
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: undefined,
      error: { detail: "Library is unavailable." },
      response: new Response(null, { status: 502 }),
    });

    render(<OperatorLibrary />);

    expect(await screen.findByText(/library is unavailable/i)).toBeInTheDocument();
  });

  it("lists a licensed framework and downloads an artifact via presigned URL", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign },
    });
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: { items: [libraryItem()], page: 1, page_size: 25, total: 1 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getExploreFrameworkDetail).mockResolvedValue({
      data: { artifacts: [{ id: "art-1", name: "playbook.pdf" }] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(downloadLicensedArtifact).mockResolvedValue({
      data: { download_url: "https://s3.test/signed" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<OperatorLibrary />);

    expect(
      await screen.findByText(/board risk operating system/i),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /playbook\.pdf/i }));

    await waitFor(() => {
      expect(vi.mocked(downloadLicensedArtifact)).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
        path: { artifact_id: "art-1", framework_id: "fw-1" },
      });
      expect(assign).toHaveBeenCalledWith("https://s3.test/signed");
    });
  });
});
