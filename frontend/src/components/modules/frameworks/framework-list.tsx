"use client";

/**
 * Contributor Framework list.
 *
 * Fetches owned Framework summaries through the generated client using the
 * in-memory access token.
 */
import Link from "next/link";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { useEffect, useState } from "react";
import {
  UploadIcon,
  ClockIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
  ArrowRightIcon,
  Cross2Icon,
} from "@radix-ui/react-icons";

import { listContributorFrameworks } from "@/lib/generated/sdk.gen";
import type { FrameworkListItem } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { ensureBrowserAccessToken } from "@/lib/auth/current-user-session";
import {
  formatFrameworkStatus,
  formatLabel,
  formatMoney,
} from "@/lib/marketplace/format";

/**
 * Maps the framework status to semantic Tailwind classes for styling indicators.
 */
function getStatusTheme(status: FrameworkListItem["status"]) {
  switch (status) {
    case "published":
      return { classes: "bg-[#16A34A]/10 text-[#16A34A] border-[#16A34A]/30" };
    case "draft":
    case "unpublished":
      return { classes: "bg-surface-2 text-foreground-muted border-border-default" };
    case "submitted":
    case "processing":
    case "pipeline_passed":
      return { classes: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" };
    case "pipeline_failed":
    case "suspended":
    default:
      return { classes: "bg-[#DC2626]/10 text-[#DC2626] border-[#DC2626]/30" };
  }
}

/**
 * Render Contributor-owned Framework summaries.
 */
export function FrameworkList() {
  const [frameworks, setFrameworks] = useState<FrameworkListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "published" | "pending" | "draft">("all");

  useEffect(() => {
    async function loadFrameworks() {
      try {
        configureBrowserClient();
        // Access tokens are memory-only, so a hard reload (e.g. straight after
        // login) leaves a valid refresh session with no bearer token. Rehydrate
        // before the call or the backend rejects it with "Missing access token".
        const hasToken = await ensureBrowserAccessToken();
        if (!hasToken) {
          setError("Your session has expired. Please log in again.");
          setLoading(false);
          return;
        }
        const result = await listContributorFrameworks({
          headers: getAccessTokenHeaders(),
        });
        if (!result.response.ok || !result.data) {
          setError(describeGeneratedError(result.error));
          setLoading(false);
          return;
        }
        setFrameworks(result.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Network error or API unavailable.");
      } finally {
        setLoading(false);
      }
    }

    void loadFrameworks();
  }, []);

  if (loading) {
    return <CardSkeleton />;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (frameworks.length === 0) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-12 text-center shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          No frameworks yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Create your first draft to begin upload and processing.
        </p>
      </div>
    );
  }

  // Calculate high-level summary metrics
  const publishedCount = frameworks.filter(fw => fw.status === "published").length;
  const draftCount = frameworks.filter(fw => fw.status === "draft" || fw.status === "unpublished").length;
  const pendingCount = frameworks.filter(fw => ["submitted", "processing", "pipeline_passed"].includes(fw.status)).length;

  // Filter frameworks list by search query and status grouping
  const filteredFrameworks = frameworks.filter((fw) => {
    const matchesSearch =
      fw.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      fw.category.toLowerCase().includes(searchQuery.toLowerCase());

    if (statusFilter === "all") return matchesSearch;
    if (statusFilter === "published") return matchesSearch && fw.status === "published";
    if (statusFilter === "draft") {
      return matchesSearch && (fw.status === "draft" || fw.status === "unpublished");
    }
    if (statusFilter === "pending") {
      return matchesSearch && ["submitted", "processing", "pipeline_passed"].includes(fw.status);
    }
    return matchesSearch;
  });

  return (
    <div className="space-y-8">
      {/* Bento Box Metrics Row */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm hover:border-accent/30 transition-all flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-surface-2">
            <UploadIcon className="h-5 w-5 text-accent" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle">Published</p>
            <p className="mt-1 font-heading text-2xl font-bold text-foreground leading-none">{publishedCount}</p>
          </div>
        </div>

        <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm hover:border-accent/30 transition-all flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-surface-2">
            <ClockIcon className="h-5 w-5 text-accent" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle">In Review</p>
            <p className="mt-1 font-heading text-2xl font-bold text-foreground leading-none">{pendingCount}</p>
          </div>
        </div>

        <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm hover:border-accent/30 transition-all flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-surface-2">
            <FileTextIcon className="h-5 w-5 text-accent" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle">Drafts</p>
            <p className="mt-1 font-heading text-2xl font-bold text-foreground leading-none">{draftCount}</p>
          </div>
        </div>
      </div>

      {/* Interactive Filters Bar */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 pointer-events-none">
            <MagnifyingGlassIcon className="h-4 w-4 text-foreground-subtle" />
          </span>
          <input
            className="w-full min-h-12 pl-10 pr-10 rounded-xl border border-border-default bg-surface-1 text-sm text-foreground placeholder:text-foreground-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search frameworks..."
            type="text"
            value={searchQuery}
          />
          {searchQuery && (
            <button
              className="absolute inset-y-0 right-0 flex items-center pr-3 text-foreground-subtle hover:text-foreground"
              onClick={() => setSearchQuery("")}
            >
              <Cross2Icon className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Filter Buttons */}
        <div className="flex flex-wrap gap-1 p-1 rounded-xl bg-surface-2 border border-border-default max-w-fit">
          {(["all", "published", "pending", "draft"] as const).map((filter) => {
            const isActive = statusFilter === filter;
            return (
              <button
                className={`px-4 py-2 text-[10px] font-bold uppercase tracking-[0.08em] rounded-lg transition-all ${
                  isActive
                    ? "bg-foreground text-background shadow-sm"
                    : "text-foreground-muted hover:text-foreground hover:bg-surface-1"
                }`}
                key={filter}
                onClick={() => setStatusFilter(filter)}
              >
                {filter === "all" ? "All" : filter === "pending" ? "In Review" : filter}
              </button>
            );
          })}
        </div>
      </div>

      {/* Grid of Bento Cards */}
      {filteredFrameworks.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-12 text-center shadow-sm">
          <p className="text-sm text-foreground-muted">No frameworks match your search or filters.</p>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredFrameworks.map((framework) => {
            const statusTheme = getStatusTheme(framework.status);
            return (
              <article
                className="group flex flex-col justify-between rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm transition-all hover:border-accent/40 hover:shadow-bento"
                key={framework.id}
              >
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle">
                      {formatLabel(framework.category)}
                    </span>
                    <span className={`inline-flex items-center rounded-badge px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.05em] border ${statusTheme.classes}`}>
                      {formatFrameworkStatus(framework.status)}
                    </span>
                  </div>

                  <Link href={`/dashboard/frameworks/${framework.id}`} className="block">
                    <h2 className="font-heading text-lg font-bold tracking-tight text-foreground line-clamp-2 group-hover:text-accent transition-colors">
                      {framework.title}
                    </h2>
                  </Link>
                </div>

                <div className="mt-6 space-y-4">
                  {/* Nested Metadata Box */}
                  <div className="rounded-xl bg-surface-2 border border-border-default/40 p-3 flex items-center justify-between text-xs text-foreground-muted">
                    <span>Version {framework.version}</span>
                    <span className="font-semibold text-foreground px-2 py-0.5 rounded bg-surface-3 border border-border-default/50">
                      {formatMoney(framework.price, framework.currency)}
                    </span>
                  </div>

                  <Link
                    className="inline-flex min-h-12 w-full items-center justify-center gap-1.5 rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
                    href={`/dashboard/frameworks/${framework.id}`}
                  >
                    Open Workspace
                    <ArrowRightIcon className="h-4 w-4 stroke-[1.5]" />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
