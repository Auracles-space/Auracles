import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrganizationsPage from "@/app/(auth)/dashboard/organizations/page";
import BecomeAttestorPage from "@/app/(auth)/dashboard/organizations/become-attestor/page";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";

const replace = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

const fail = () => ({
  data: undefined,
  error: { detail: "x" },
  request: new Request("http://t"),
  response: new Response(null, { status: 500 }),
});

const org = (id: string, role: string, capabilities = {}) => ({
  org: { id, name: `Org ${id}`, slug: id, country: "US" },
  role,
  capabilities,
});

describe("BecomeAttestorPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("redirects to the single eligible organization's attestor tab", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner")] }) as never,
    );

    render(<BecomeAttestorPage />);

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith("/dashboard/organizations/a/attestor");
    });
  });

  it("renders the picker when two or more organizations are eligible", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner"), org("b", "admin")] }) as never,
    );

    render(<BecomeAttestorPage />);

    await waitFor(() => {
      expect(screen.getByText(/Choose an organization/i)).toBeInTheDocument();
    });
    expect(replace).not.toHaveBeenCalled();
  });

  it("opens the create dialog when no organization is eligible", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("c", "member")] }) as never,
    );

    render(<BecomeAttestorPage />);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  it("shows an error with retry when loading fails", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(fail() as never);

    render(<BecomeAttestorPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
    });
  });
});

describe("OrganizationsPage become-attestor CTA", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links to the become-attestor entry route in the header", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner")] }) as never,
    );

    render(<OrganizationsPage />);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /Become an Attestor/i })).toHaveAttribute(
        "href",
        "/dashboard/organizations/become-attestor",
      );
    });
  });
});
