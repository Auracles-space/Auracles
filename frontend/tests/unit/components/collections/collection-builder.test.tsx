import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionBuilder } from "@/components/modules/collections/collection-builder";
import {
  listContributorFrameworks,
  listMyCollections,
} from "@/lib/generated/sdk.gen";
import type { CollectionResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "Collections are unavailable."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addCollectionMemberV1CollectionsCollectionIdMembersPost: vi.fn(),
  createCollection: vi.fn(),
  listContributorFrameworks: vi.fn(),
  listMyCollections: vi.fn(),
  publishCollectionV1CollectionsCollectionIdPublishPost: vi.fn(),
  removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete: vi.fn(),
  unpublishCollectionV1CollectionsCollectionIdUnpublishPost: vi.fn(),
}));

describe("CollectionBuilder", () => {
  function buildCollection(
    overrides: Partial<CollectionResponse> = {},
  ): CollectionResponse {
    return {
      bundle_price: "700.00",
      contributor_id: "00000000-0000-4000-8000-000000000001",
      created_at: "2026-06-11T00:00:00Z",
      currency: "USD",
      description: "Discounted diligence controls.",
      id: "00000000-0000-4000-8000-000000000301",
      members: [],
      status: "draft",
      title: "Diligence Control Collection",
      updated_at: "2026-06-11T00:00:00Z",
      ...overrides,
    };
  }

  beforeEach(() => {
    vi.mocked(listContributorFrameworks).mockReset();
    vi.mocked(listMyCollections).mockReset();
    vi.mocked(listContributorFrameworks).mockResolvedValue({
      data: [],
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("hides the collection switcher when the contributor has no collections", async () => {
    vi.mocked(listMyCollections).mockResolvedValue({
      data: { collections: [] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CollectionBuilder />);

    await waitFor(() => {
      expect(
        screen.getByText(
          "Create a draft Collection to begin bundling Frameworks.",
        ),
      ).toBeInTheDocument();
    });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows the collection switcher when collections exist", async () => {
    vi.mocked(listMyCollections).mockResolvedValue({
      data: {
        collections: [buildCollection()],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CollectionBuilder />);

    expect(
      await screen.findByRole("combobox", { name: "Select collection" }),
    ).toBeInTheDocument();
  });

  it("disables publish for draft bundles that are not yet publishable", async () => {
    vi.mocked(listMyCollections).mockResolvedValue({
      data: {
        collections: [
          buildCollection({
            bundle_price: "700.00",
            members: [
              {
                currency: "USD",
                framework_id: "00000000-0000-4000-8000-000000000111",
                price: "400.00",
                status: "published",
                title: "Control Framework A",
              },
            ],
          }),
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CollectionBuilder />);

    expect(await screen.findByRole("button", { name: "Publish bundle" })).toBeDisabled();
  });

  it("enables publish for draft bundles that satisfy bundle readiness rules", async () => {
    vi.mocked(listMyCollections).mockResolvedValue({
      data: {
        collections: [
          buildCollection({
            bundle_price: "700.00",
            members: [
              {
                currency: "USD",
                framework_id: "00000000-0000-4000-8000-000000000111",
                price: "400.00",
                status: "published",
                title: "Control Framework A",
              },
              {
                currency: "USD",
                framework_id: "00000000-0000-4000-8000-000000000112",
                price: "500.00",
                status: "published",
                title: "Control Framework B",
              },
            ],
          }),
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CollectionBuilder />);

    expect(await screen.findByRole("button", { name: "Publish bundle" })).toBeEnabled();
  });
});
