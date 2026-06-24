import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionBuilder } from "@/components/modules/collections/collection-builder";
import {
  addCollectionMemberV1CollectionsCollectionIdMembersPost,
  createCollection,
  listContributorFrameworks,
  listMyCollections,
  publishCollectionV1CollectionsCollectionIdPublishPost,
  removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete,
  unpublishCollectionV1CollectionsCollectionIdUnpublishPost,
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

  const ok = <T,>(data: T) => ({
    data,
    error: undefined,
    request: new Request("http://testserver"),
    response: new Response(null, { status: 200 }),
  });

  it("creates a new draft collection from the form", async () => {
    vi.mocked(listMyCollections).mockResolvedValue(
      ok({ collections: [buildCollection()] }),
    );
    vi.mocked(createCollection).mockResolvedValue(
      ok(buildCollection({ id: "new-collection", title: "Fresh Bundle" })),
    );

    render(<CollectionBuilder />);
    await screen.findByRole("combobox", { name: "Select collection" });

    fireEvent.change(screen.getByPlaceholderText(/collection title/i), {
      target: { value: "Fresh Bundle" },
    });
    fireEvent.change(screen.getByPlaceholderText(/describe the bundle/i), {
      target: { value: "A brand new pack." },
    });
    fireEvent.change(screen.getByPlaceholderText(/bundle price/i), {
      target: { value: "250.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));

    await waitFor(() =>
      expect(vi.mocked(createCollection)).toHaveBeenCalledTimes(1),
    );
  });

  it("adds a framework to the active bundle", async () => {
    vi.mocked(listMyCollections).mockResolvedValue(
      ok({ collections: [buildCollection()] }),
    );
    vi.mocked(listContributorFrameworks).mockResolvedValue(
      ok([
        {
          id: "00000000-0000-4000-8000-000000000111",
          title: "Control Framework A",
          status: "published",
        },
      ]) as never,
    );
    vi.mocked(
      addCollectionMemberV1CollectionsCollectionIdMembersPost,
    ).mockResolvedValue(ok(buildCollection()));

    render(<CollectionBuilder />);
    await screen.findByRole("combobox", { name: "Select collection" });

    // The framework picker is the combobox containing the "Select a published
    // Framework" placeholder option (the named one is the collection switcher).
    const frameworkSelect = screen
      .getByRole("option", { name: /select a published framework/i })
      .closest("select") as HTMLSelectElement;
    fireEvent.change(frameworkSelect, {
      target: { value: "00000000-0000-4000-8000-000000000111" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add to bundle/i }));

    await waitFor(() =>
      expect(
        vi.mocked(addCollectionMemberV1CollectionsCollectionIdMembersPost),
      ).toHaveBeenCalledTimes(1),
    );
  });

  it("publishes a ready bundle", async () => {
    vi.mocked(listMyCollections).mockResolvedValue(
      ok({
        collections: [
          buildCollection({
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
      }),
    );
    vi.mocked(
      publishCollectionV1CollectionsCollectionIdPublishPost,
    ).mockResolvedValue(ok(buildCollection({ status: "published" })));

    render(<CollectionBuilder />);
    fireEvent.click(await screen.findByRole("button", { name: "Publish bundle" }));

    await waitFor(() =>
      expect(
        vi.mocked(publishCollectionV1CollectionsCollectionIdPublishPost),
      ).toHaveBeenCalledTimes(1),
    );
  });

  it("removes a member and unpublishes a published bundle", async () => {
    const publishedBundle = buildCollection({
      status: "published",
      members: [
        {
          currency: "USD",
          framework_id: "00000000-0000-4000-8000-000000000111",
          price: "400.00",
          status: "published",
          title: "Control Framework A",
        },
      ],
    });
    vi.mocked(listMyCollections).mockResolvedValue(
      ok({ collections: [publishedBundle] }),
    );
    vi.mocked(
      removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete,
    ).mockResolvedValue(ok(publishedBundle));
    vi.mocked(
      unpublishCollectionV1CollectionsCollectionIdUnpublishPost,
    ).mockResolvedValue(ok(buildCollection({ status: "unpublished" })));

    render(<CollectionBuilder />);
    fireEvent.click(await screen.findByRole("button", { name: /^Remove$/ }));
    await waitFor(() =>
      expect(
        vi.mocked(
          removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete,
        ),
      ).toHaveBeenCalledTimes(1),
    );

    fireEvent.click(screen.getByRole("button", { name: /^Unpublish$/ }));
    await waitFor(() =>
      expect(
        vi.mocked(unpublishCollectionV1CollectionsCollectionIdUnpublishPost),
      ).toHaveBeenCalledTimes(1),
    );
  });
});
