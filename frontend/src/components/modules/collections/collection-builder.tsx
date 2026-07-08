"use client";

/**
 * Contributor Collection builder.
 *
 * Lets Contributors create bundle drafts, add owned published Frameworks,
 * publish valid bundles, and unpublish bundles that should stop new sales.
 */
import { useEffect, useMemo, useState } from "react";

import {
  addCollectionMemberV1CollectionsCollectionIdMembersPost,
  createCollection,
  listContributorFrameworks,
  listMyCollections,
  publishCollectionV1CollectionsCollectionIdPublishPost,
  removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete,
  unpublishCollectionV1CollectionsCollectionIdUnpublishPost,
} from "@/lib/generated/sdk.gen";
import type {
  CollectionResponse,
  FrameworkListItem,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type CollectionFormState = {
  title: string;
  description: string;
  bundlePrice: string;
};

const emptyForm: CollectionFormState = {
  title: "",
  description: "",
  bundlePrice: "",
};

/**
 * Render the Contributor collection builder.
 */
export function CollectionBuilder() {
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [frameworks, setFrameworks] = useState<FrameworkListItem[]>([]);
  const [form, setForm] = useState<CollectionFormState>(emptyForm);
  const [selectedFrameworkId, setSelectedFrameworkId] = useState<string>("");
  const [activeCollectionId, setActiveCollectionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const activeCollection = useMemo(
    () => collections.find((collection) => collection.id === activeCollectionId),
    [activeCollectionId, collections],
  );
  const activeCollectionMemberValue = useMemo(() => {
    if (!activeCollection) {
      return 0;
    }

    return activeCollection.members.reduce((total, member) => {
      const price = Number(member.price);
      return Number.isFinite(price) ? total + price : total;
    }, 0);
  }, [activeCollection]);
  const canPublishActiveCollection = useMemo(() => {
    if (!activeCollection || activeCollection.status === "published") {
      return false;
    }

    const bundlePrice = Number(activeCollection.bundle_price);
    const hasEnoughMembers = activeCollection.members.length >= 2;
    const allMembersPublished = activeCollection.members.every(
      (member) => member.status === "published",
    );

    return (
      Number.isFinite(bundlePrice) &&
      hasEnoughMembers &&
      allMembersPublished &&
      bundlePrice < activeCollectionMemberValue
    );
  }, [activeCollection, activeCollectionMemberValue]);
  const publishedFrameworks = frameworks.filter(
    (framework) => framework.status === "published",
  );

  async function refresh() {
    configureBrowserClient();
    const [collectionsResult, frameworksResult] = await Promise.all([
      listMyCollections({ headers: getAccessTokenHeaders() }),
      listContributorFrameworks({ headers: getAccessTokenHeaders() }),
    ]);
    if (!collectionsResult.response.ok || !collectionsResult.data) {
      setError(describeGeneratedError(collectionsResult.error));
      return;
    }
    if (!frameworksResult.response.ok || !frameworksResult.data) {
      setError(describeGeneratedError(frameworksResult.error));
      return;
    }
    setCollections(collectionsResult.data.collections);
    setFrameworks(frameworksResult.data);
    setActiveCollectionId((current) => {
      if (
        current &&
        collectionsResult.data.collections.some(
          (item: CollectionResponse) => item.id === current,
        )
      ) {
        return current;
      }
      return collectionsResult.data.collections[0]?.id ?? null;
    });
  }

  useEffect(() => {
    async function load() {
      try {
        await refresh();
      } catch {
        setError("Collections are unavailable.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  async function handleCreate() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await createCollection({
      body: {
        bundle_price: form.bundlePrice,
        currency: "USD",
        description: form.description,
        title: form.title,
      },
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setForm(emptyForm);
    setCollections((current) => [result.data!, ...current]);
    setActiveCollectionId(result.data.id);
  }

  async function mutateCollection(
    action: () => Promise<{ response: Response; data?: CollectionResponse }>,
  ) {
    setError(null);
    setSubmitting(true);
    const result = await action();
    setSubmitting(false);
    if (!result.response.ok || !result.data) {
      setError("Collection update failed.");
      return;
    }
    setCollections((current) =>
      current.map((collection) =>
        collection.id === result.data!.id ? result.data! : collection,
      ),
    );
  }

  async function handleAddMember() {
    if (!activeCollection || !selectedFrameworkId) {
      return;
    }
    await mutateCollection(() =>
      addCollectionMemberV1CollectionsCollectionIdMembersPost({
        body: { framework_id: selectedFrameworkId },
        headers: getAccessTokenHeaders(),
        path: { collection_id: activeCollection.id },
      }),
    );
    setSelectedFrameworkId("");
  }

  async function handleRemoveMember(frameworkId: string) {
    if (!activeCollection) {
      return;
    }
    await mutateCollection(() =>
      removeCollectionMemberV1CollectionsCollectionIdMembersFrameworkIdDelete({
        headers: getAccessTokenHeaders(),
        path: {
          collection_id: activeCollection.id,
          framework_id: frameworkId,
        },
      }),
    );
  }

  async function handlePublish() {
    if (!activeCollection) {
      return;
    }
    await mutateCollection(() =>
      publishCollectionV1CollectionsCollectionIdPublishPost({
        headers: getAccessTokenHeaders(),
        path: { collection_id: activeCollection.id },
      }),
    );
  }

  async function handleUnpublish() {
    if (!activeCollection) {
      return;
    }
    await mutateCollection(() =>
      unpublishCollectionV1CollectionsCollectionIdUnpublishPost({
        headers: getAccessTokenHeaders(),
        path: { collection_id: activeCollection.id },
      }),
    );
  }

  if (loading) {
    return <CardSkeleton />;
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          New Collection
        </h2>
        <div className="mt-6 grid gap-4">
          <input
            className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
            onChange={(event) =>
              setForm((current) => ({ ...current, title: event.target.value }))
            }
            placeholder="Collection title"
            value={form.title}
          />
          <textarea
            className="min-h-32 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                description: event.target.value,
              }))
            }
            placeholder="Describe the bundle"
            value={form.description}
          />
          <input
            className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
            inputMode="decimal"
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                bundlePrice: event.target.value,
              }))
            }
            placeholder="Bundle price, USD"
            value={form.bundlePrice}
          />
          <button
            className="mt-2 min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={
              submitting || !form.title || !form.description || !form.bundlePrice
            }
            onClick={handleCreate}
            type="button"
          >
            Create draft
          </button>
        </div>
        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
      </section>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-heading text-2xl font-bold text-foreground">
              Manage Bundles
            </h2>
            <p className="mt-2 text-sm text-foreground-muted">
              Bundles must include at least two published Frameworks and be
              priced below member value before publish.
            </p>
          </div>
          {collections.length > 0 ? (
            <select
              aria-label="Select collection"
              className="min-h-12 min-w-[200px] rounded-xl border border-border-default bg-surface-2 px-4 text-sm font-semibold text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
              onChange={(event) => setActiveCollectionId(event.target.value)}
              value={activeCollectionId ?? ""}
            >
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.title}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {activeCollection ? (
          <div className="mt-8 grid gap-6">
            <div className="rounded-xl border border-border-default bg-surface-2 p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                {formatLabel(activeCollection.status)}
              </p>
              <h3 className="mt-2 font-heading text-2xl font-bold text-foreground">
                {activeCollection.title}
              </h3>
              <p className="mt-3 text-sm leading-6 text-foreground-muted">
                {activeCollection.description}
              </p>
              <div className="mt-4 inline-flex items-center rounded-xl border border-success/30 bg-success/10 px-3 py-1.5 text-sm font-semibold text-success">
                {formatMoney(
                  activeCollection.bundle_price,
                  activeCollection.currency,
                )}
              </div>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <select
                className="min-h-12 flex-1 rounded-xl border border-border-default bg-surface-2 px-4 text-sm text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
                onChange={(event) => setSelectedFrameworkId(event.target.value)}
                value={selectedFrameworkId}
              >
                <option value="">Select a published Framework...</option>
                {publishedFrameworks.map((framework) => (
                  <option key={framework.id} value={framework.id}>
                    {framework.title}
                  </option>
                ))}
              </select>
              <button
                className="min-h-12 rounded-xl border border-border-strong bg-background px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-1 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={submitting || !selectedFrameworkId}
                onClick={handleAddMember}
                type="button"
              >
                Add to bundle
              </button>
            </div>

            <div className="grid gap-3">
              {activeCollection.members.map((member) => (
                <div
                  className="group flex flex-col gap-3 rounded-xl border border-border-default bg-surface-2 p-4 transition-colors hover:bg-surface-1 sm:flex-row sm:items-center sm:justify-between"
                  key={member.framework_id}
                >
                  <div>
                    <p className="font-semibold text-foreground transition-colors group-hover:text-accent">
                      {member.title}
                    </p>
                    <p className="mt-1 text-sm text-foreground-muted">
                      {formatLabel(member.status)} ·{" "}
                      <span className="font-medium text-foreground">
                        {formatMoney(member.price, member.currency)}
                      </span>
                    </p>
                  </div>
                  <button
                    className="min-h-12 rounded-xl border border-error/50 bg-error/5 px-4 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={submitting}
                    onClick={() => handleRemoveMember(member.framework_id)}
                    type="button"
                  >
                    Remove
                  </button>
                </div>
              ))}
              {activeCollection.members.length === 0 && (
                <div className="rounded-xl border border-dashed border-border-strong p-8 text-center text-sm text-foreground-muted">
                  No frameworks added to this bundle yet.
                </div>
              )}
            </div>

            <div className="mt-2 flex flex-col gap-4 border-t border-border-strong pt-6 sm:flex-row sm:items-center sm:justify-end">
              <button
                className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={submitting || activeCollection.status !== "published"}
                onClick={handleUnpublish}
                type="button"
              >
                Unpublish
              </button>
              <button
                className="min-h-12 rounded-xl bg-foreground px-8 text-sm font-bold text-background outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={submitting || !canPublishActiveCollection}
                onClick={handlePublish}
                type="button"
              >
                Publish bundle
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-8 rounded-xl border border-dashed border-border-strong p-12 text-center text-sm text-foreground-muted">
            Create a draft Collection to begin bundling Frameworks.
          </div>
        )}
      </section>
    </div>
  );
}
