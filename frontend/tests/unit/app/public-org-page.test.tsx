/**
 * Public organization profile route.
 *
 * Capabilities render through the shared status vocabulary, the website
 * link only appears for http(s) URLs, and the action link meets the 44px
 * touch target.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PublicOrganizationPage from "@/app/(public)/orgs/[slug]/page";
import { getPublicOrgV1OrgsSlugGet } from "@/lib/generated/sdk.gen";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ getPublicOrgV1OrgsSlugGet: vi.fn() }));

function org(overrides: Record<string, unknown> = {}) {
  return {
    name: "Meridian Audit",
    slug: "meridian",
    country: "NG",
    description: "Independent assurance for Lagos operators.",
    logo_key: null,
    logo_url: null,
    website: "https://meridian.example",
    member_count: 4,
    created_at: "2026-02-01T00:00:00Z",
    active_capabilities: ["attestor", "contributor"],
    ...overrides,
  };
}

function ok<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://t"),
    response: new Response(null, { status: 200 }),
  };
}

async function renderPage() {
  render(await PublicOrganizationPage({ params: Promise.resolve({ slug: "meridian" }) }));
}

describe("PublicOrganizationPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders capabilities as status pills with their labels", async () => {
    vi.mocked(getPublicOrgV1OrgsSlugGet).mockResolvedValue(ok(org()) as never);
    await renderPage();

    const pill = screen.getByText("Attestor");
    expect(pill.className).toMatch(/rounded-badge/);
    expect(screen.getByText("Contributor")).toBeInTheDocument();
  });

  it("links the website with a 44px target when it is an http(s) URL", async () => {
    vi.mocked(getPublicOrgV1OrgsSlugGet).mockResolvedValue(ok(org()) as never);
    await renderPage();

    const link = screen.getByRole("link", { name: /website/i });
    expect(link).toHaveAttribute("href", "https://meridian.example");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link.className).toMatch(/min-h-11/);
  });

  it("omits the website link when the URL is not http(s)", async () => {
    vi.mocked(getPublicOrgV1OrgsSlugGet).mockResolvedValue(
      ok(org({ website: "javascript:alert(1)" })) as never,
    );
    await renderPage();

    expect(screen.queryByRole("link", { name: /website/i })).toBeNull();
    expect(screen.getByText("Meridian Audit")).toBeInTheDocument();
  });
});
