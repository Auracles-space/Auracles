/**
 * Shared response fixtures and SDK result helpers for the admin
 * organization detail tests.
 */
import type {
  AdminOrgAttestationsResponse,
  AdminOrgAuditResponse,
  AdminOrgFinancialsResponse,
  AdminOrgFrameworksResponse,
  AdminOrgMembersResponse,
  AdminOrgOverviewResponse,
  AdminOrgVerificationResponse,
} from "@/lib/generated/types.gen";

/** Wrap data in the generated client's success envelope. */
export function ok<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://t"),
    response: new Response(null, { status: 200 }),
  } as never;
}

/** Build the generated client's failure envelope. */
export function fail(status = 500) {
  return {
    data: undefined,
    error: { detail: "Server unavailable." },
    request: new Request("http://t"),
    response: new Response(null, { status }),
  } as never;
}

/** An active organization overview, overridable per test. */
export function overview(overrides: Partial<AdminOrgOverviewResponse> = {}): AdminOrgOverviewResponse {
  return {
    id: "org-1",
    name: "Kano Audit Partners",
    slug: "kano-audit",
    country: "NG",
    created_at: "2026-09-01T09:00:00Z",
    description: null,
    website: null,
    kyb_status: "verified",
    kyb_submitted_at: "2026-09-02T09:00:00Z",
    kyb_verified_at: "2026-09-03T09:00:00Z",
    legal_name: "Kano Audit Partners Ltd",
    registration_number: "RC-778812",
    member_count: 4,
    owners: [
      { display_name: "Amina Bello", email: "amina@kano.example", member_id: "m-1", user_id: "u-1" },
    ],
    capabilities: [
      { capability: "contributor", status: "active", status_reason: null },
      { capability: "operator", status: "suspended", status_reason: "Two chargebacks this month." },
    ],
    suspended_at: null,
    suspended_by: null,
    suspension_reason: null,
    deactivated_at: null,
    deactivated_by: null,
    deactivation_reason: null,
    ...overrides,
  };
}

export const MEMBERS: AdminOrgMembersResponse = {
  pending_invitation_count: 2,
  members: [
    {
      display_name: "Tunde Okafor",
      email: "tunde@kano.example",
      joined_at: "2026-09-04T10:00:00Z",
      member_id: "m-2",
      role: "admin",
      teams: [{ id: "t-1", name: "Assurance" }],
      user_id: "u-2",
    },
  ],
};

export const VERIFICATION: AdminOrgVerificationResponse = {
  kyb_status: "pending",
  legal_name: "Kano Audit Partners Ltd",
  registration_number: "RC-778812",
  address: { line1: "12 Bompai Road", city: "Kano", country: "NG" },
  kyb_submitted_at: "2026-09-02T09:00:00Z",
  kyb_verified_at: null,
  kyb_review_notes: "Tax document was blurry on first submission.",
  tax_document_type: "tin_certificate",
  documents: [
    { kind: "incorporation", file_name: "cac.pdf", download_url: "https://s3.example/cac.pdf?sig=1" },
    { kind: "tax", file_name: "tin.pdf", download_url: null },
  ],
};

export const FINANCIALS: AdminOrgFinancialsResponse = {
  currency: "NGN",
  available_balance: "150000.00",
  pending_balance: "25000.00",
  payouts_summary: { completed_total: "900000.00", last_payout_at: "2026-09-10T00:00:00Z", pending_count: 1 },
  purchases_summary: { completed_count: 7, failed_count: 1, total_spent: "420000.00" },
  recent_payouts: [
    {
      payout_id: "p-1",
      amount: "50000.00",
      currency: "NGN",
      status: "completed",
      initiated_at: "2026-09-09T00:00:00Z",
      completed_at: "2026-09-10T00:00:00Z",
      provider: "paystack",
    },
  ],
  recent_transactions: [
    {
      transaction_id: "tx-1",
      amount: "12000.00",
      currency: "NGN",
      status: "failed",
      transaction_type: "framework_purchase",
      created_at: "2026-09-08T00:00:00Z",
    },
  ],
};

export const FRAMEWORKS: AdminOrgFrameworksResponse = {
  frameworks: [
    { id: "fw-1", title: "Supplier Risk Playbook", status: "published", created_at: "2026-09-05T00:00:00Z" },
    { id: "fw-2", title: "Draft Controls Map", status: "draft", created_at: "2026-09-06T00:00:00Z" },
  ],
  licenses: [
    {
      license_id: "l-1",
      framework_id: "fw-9",
      framework_title: "Payroll Audit Kit",
      license_type: "team",
      status: "active",
      grant_count: 3,
      created_at: "2026-09-07T00:00:00Z",
    },
  ],
};

export const ATTESTATIONS: AdminOrgAttestationsResponse = {
  counts: { in_flight: 1, completed: 5 },
  attestations: [
    {
      id: "a-1",
      status: "report_submitted",
      target_title: "Supplier Risk Playbook",
      reviewing_member_display_name: "Tunde Okafor",
      completion_due_at: "2026-09-20T00:00:00Z",
      created_at: "2026-09-11T00:00:00Z",
    },
  ],
};

/** One audit page with a total that implies a second page. */
export function auditPage(page = 1): AdminOrgAuditResponse {
  return {
    page,
    page_size: 20,
    total: 25,
    items: [
      {
        log_id: `log-${page}`,
        action: page === 1 ? "org_kyb_document_viewed" : "org_suspended",
        actor: page === 1 ? { id: "u-9", display_name: "Grace Admin" } : null,
        created_at: "2026-09-12T14:30:00Z",
        target_type: "organization",
        target_id: "org-1",
        metadata: { kind: "incorporation" },
      },
    ],
  };
}
