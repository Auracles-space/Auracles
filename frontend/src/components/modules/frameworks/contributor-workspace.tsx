"use client";

/**
 * Contributor workspace: Frameworks and Collections as two tabs of one page.
 *
 * A Collection is a bundle of Frameworks, so the builder belongs beside the
 * list it draws from rather than behind a nav slot of its own — QA asked why a
 * Contributor had to leave Frameworks to bundle them. The old
 * `/dashboard/collections` route redirects here with `?tab=collections`, so
 * existing links keep working and there is only one builder.
 *
 * Maps to: FR-FWK (framework management), FR-EXP (collection bundling).
 */
import Link from "next/link";
import { PlusIcon } from "@radix-ui/react-icons";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CollectionBuilder } from "@/components/modules/collections/collection-builder";
import { FrameworkList } from "@/components/modules/frameworks/framework-list";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";

type WorkspaceTab = "frameworks" | "collections";

/** Narrow a raw query value to a known tab. */
function isTab(value: string | null): value is WorkspaceTab {
  return value === "frameworks" || value === "collections";
}

const TAB_COPY: Record<WorkspaceTab, { title: string; blurb: string }> = {
  frameworks: {
    title: "Frameworks",
    blurb:
      "Manage, version, and monitor the publication and review pipelines for your reusable operational frameworks.",
  },
  collections: {
    title: "Collections",
    blurb:
      "Bundle published Frameworks into discounted Collections for marketplace operators.",
  },
};

/**
 * Render the Contributor's Frameworks and Collections workspace.
 */
export function ContributorWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams?.get("tab") ?? null;
  const [active, setActive] = useState<WorkspaceTab>(
    isTab(requested) ? requested : "frameworks",
  );

  // Follow the URL when it changes underneath us — a redirect from the old
  // Collections route, or the browser's back button.
  useEffect(() => {
    if (isTab(requested) && requested !== active) {
      setActive(requested);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  function select(id: string): void {
    if (!isTab(id)) {
      return;
    }
    setActive(id);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", id);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  const copy = TAB_COPY[active];

  return (
    <div className="mx-auto w-full max-w-[1280px]">
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
            Contributor dashboard
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold tracking-[-0.02em] text-foreground md:text-4xl">
            {copy.title}
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-foreground-muted">
            {copy.blurb}
          </p>
        </div>
        {active === "frameworks" ? (
          <Link
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-foreground px-5 py-2.5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
            href="/dashboard/frameworks/new"
          >
            <PlusIcon className="h-4 w-4 stroke-[1.5]" />
            Create framework
          </Link>
        ) : null}
      </header>

      <Tabs
        activeId={active}
        label="Contributor workspace"
        onChange={select}
        tabs={[
          { id: "frameworks", label: "Frameworks" },
          { id: "collections", label: "Collections" },
        ]}
      />

      <div
        aria-labelledby={tabId(active)}
        className="mt-6"
        id={tabPanelId(active)}
        role="tabpanel"
      >
        {active === "frameworks" ? (
          <FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />
        ) : (
          <CollectionBuilder />
        )}
      </div>
    </div>
  );
}
