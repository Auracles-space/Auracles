/**
 * Admin Framework detail — a held Framework is readable, its blocking
 * Artifact is named, and the file itself is never offered.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFrameworkDetail } from "@/components/modules/admin/admin-framework-detail";
import { getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "Could not load this Framework."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet: vi.fn(),
}));

const FRAMEWORK_ID = "11111111-1111-4111-8111-111111111111";
const HELD_ARTIFACT_ID = "22222222-2222-4222-8222-222222222222";

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: HELD_ARTIFACT_ID,
    name: "onboarding-playbook.pdf",
    mime_type: "application/pdf",
    file_size: 4096,
    scan_status: "clean",
    processing_status: "flagged_pii",
    pii_detected: true,
    pii_review_needed: true,
    current_for_framework: true,
    blocking: true,
    pii_types_found: ["email", "phone_number"],
    auto_redacted: true,
    redaction_status: "generated",
    redaction_accepted: false,
    redaction_available: true,
    rarity_score: null,
    created_at: "2026-09-27T09:00:00Z",
    ...overrides,
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    framework_id: FRAMEWORK_ID,
    title: "Held Onboarding Framework",
    description: "Held for PII review.",
    version: "1.0.0",
    status: "pipeline_failed",
    category: "operations",
    sector: "technology",
    industry: "software",
    business_function: "operations",
    jurisdiction: null,
    complexity: 3,
    tags: ["onboarding"],
    price: "150.00",
    org_price: null,
    currency: "NGN",
    license_types: ["single_user"],
    contributor_id: "33333333-3333-4333-8333-333333333333",
    contributor_name: "Adaeze Okafor",
    contributor_email: "adaeze@example.com",
    organization_id: null,
    organization_name: null,
    rejection_reason: null,
    pipeline_failure_reasons: { pii: [HELD_ARTIFACT_ID] },
    last_pipeline_run_at: "2026-09-27T09:05:00Z",
    published_at: null,
    created_at: "2026-09-24T09:00:00Z",
    updated_at: "2026-09-27T09:05:00Z",
    artifacts: [artifact()],
    timeline: [
      {
        action: "framework_submitted",
        actor_id: "33333333-3333-4333-8333-333333333333",
        actor_name: "Adaeze Okafor",
        created_at: "2026-09-24T10:00:00Z",
        metadata: { version: "1.0.0" },
      },
    ],
    action_links: [
      {
        rel: "override_rarity_block",
        method: "POST",
        path: `/v1/admin/frameworks/${FRAMEWORK_ID}/rarity-block/override`,
        actor_role: "admin",
      },
    ],
    ...overrides,
  };
}

function respond(body: Record<string, unknown>) {
  vi.mocked(getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet).mockResolvedValue({
    data: body,
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("AdminFrameworkDetail", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a held Framework, its owner, and which Artifact is blocking it", async () => {
    // A pipeline_failed Framework is in no list an admin can reach; before
    // this page the only way to see one was the database.
    respond(detail());
    render(<AdminFrameworkDetail frameworkId={FRAMEWORK_ID} />);

    expect(await screen.findByText("Held Onboarding Framework")).toBeInTheDocument();
    expect(screen.getByText("Processing failed")).toBeInTheDocument();
    expect(screen.getByText("Adaeze Okafor")).toBeInTheDocument();
    expect(screen.getByText("onboarding-playbook.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Blocking/i)).toBeInTheDocument();
    expect(screen.getByText(/PII found/i)).toBeInTheDocument();
    expect(screen.getByText("Email, Phone Number")).toBeInTheDocument();
  });

  it("says the owner must clear a PII hold, because an admin cannot", async () => {
    // The admin has no button for a PII review by design: the redaction is
    // accepted or removed by the Framework's owner.
    respond(detail());
    render(<AdminFrameworkDetail frameworkId={FRAMEWORK_ID} />);

    expect(
      await screen.findByText(/Adaeze Okafor accepts or removes the redaction/i),
    ).toBeInTheDocument();
  });

  it("never offers the file, only the findings", async () => {
    respond(detail());
    render(<AdminFrameworkDetail frameworkId={FRAMEWORK_ID} />);

    await screen.findByText("onboarding-playbook.pdf");
    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/frameworks\/held/)).not.toBeInTheDocument();
  });

  it("renders the audit timeline so an admin can see who did what", async () => {
    respond(detail());
    render(<AdminFrameworkDetail frameworkId={FRAMEWORK_ID} />);

    expect(await screen.findByText(/Framework submitted/i)).toBeInTheDocument();
  });

  it("surfaces a load failure instead of an empty page", async () => {
    vi.mocked(getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet).mockResolvedValue({
      data: undefined,
      error: { detail: "Framework not found." },
      response: new Response(null, { status: 404 }),
    } as never);
    render(<AdminFrameworkDetail frameworkId={FRAMEWORK_ID} />);

    await waitFor(() =>
      expect(screen.getByText("Could not load this Framework.")).toBeInTheDocument(),
    );
  });
});
