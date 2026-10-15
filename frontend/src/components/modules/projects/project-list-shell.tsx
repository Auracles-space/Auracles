"use client";

/**
 * Authenticated Projects landing shell.
 *
 * Operators see their posted Projects. Contributors see the open Projects they
 * can bid on plus "My engagements" — Projects they were assigned via an accepted
 * Proposal, which have left the open feed. All lists use the generated OpenAPI
 * client.
 */
import { Pencil1Icon } from "@radix-ui/react-icons";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { authTokenStore } from "@/lib/auth/token-store";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { ProjectDeleteAction } from "@/components/modules/projects/project-delete-action";
import { Tabs, tabId, tabPanelId, type TabItem } from "@/components/ui/tabs";
import { listOrgProjects, listProjects } from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";
import type { ProjectResponse } from "@/lib/generated/types.gen";
import type { ProjectApiMode } from "@/lib/projects/project-api-mode";

/**
 * Projects fetched per page.
 *
 * Matches the API's own default so the first request is the one the backend
 * would have served anyway. The list used to send no page at all, which took
 * that default and then offered no way to reach anything beyond it.
 */
const PAGE_SIZE = 20;

/**
 * Render status text in a compact operational label.
 */
function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

/**
 * Render one Project row.
 */
function ProjectCard({
  canDelete,
  basePath,
  mode,
  onDeleted,
  project,
}: {
  canDelete: boolean;
  basePath: string;
  mode: ProjectApiMode;
  onDeleted: () => void;
  project: ProjectResponse;
}) {
  return (
    <div className="relative">
      <Link
        className={`block rounded-xl border border-border-default bg-surface-1 p-6 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors hover:border-border-strong ${canDelete && project.status === "open" ? "pb-20" : ""}`}
        href={`${basePath}/${project.id}`}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-heading text-lg font-semibold text-foreground">
              {project.title}
            </h3>
            <p className="mt-1 line-clamp-2 text-sm leading-6 text-foreground-muted">
              {project.description}
            </p>
            {project.operator_name ? (
              <p className="mt-2 text-xs text-foreground-subtle">
                Posted by {project.operator_name}
              </p>
            ) : null}
          </div>
          <span className="rounded-md border border-[#2563EB]/30 bg-[#2563EB]/10 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-[#2563EB]">
            {statusLabel(project.status)}
          </span>
        </div>
        <dl className="mt-4 grid gap-3 text-sm text-foreground-muted sm:grid-cols-3">
          <div>
            <dt className="text-xs uppercase tracking-[0.05em]">Budget</dt>
            <dd className="font-semibold text-foreground">
              {formatMoney(project.budget_min, project.currency)} –{" "}
              {formatMoney(project.budget_max, project.currency)}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.05em]">Category</dt>
            <dd className="font-semibold text-foreground">{project.category}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.05em]">Plan</dt>
            <dd className="font-semibold text-foreground">
              {statusLabel(project.milestone_plan_status)}
            </dd>
          </div>
        </dl>
      </Link>
      {canDelete && project.status === "open" ? (
        <div className="absolute bottom-4 right-4 flex items-center gap-2">
          {/* Outside the card's Link, because a link cannot nest in a link. */}
          <Link
            aria-label={`Edit ${project.title}`}
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground-muted outline-none transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
            href={`${basePath}/${project.id}/edit`}
          >
            <Pencil1Icon className="h-4 w-4" />
          </Link>
          <ProjectDeleteAction
            mode={mode}
            onDeleted={onDeleted}
            projectId={project.id}
            projectTitle={project.title}
            variant="icon"
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * Render a tab panel's Project list, skeleton, or empty state.
 *
 * @param projects - Projects to render.
 * @param loading - Whether the list is still loading.
 * @param emptyText - Directional copy shown when the list is empty.
 */
function ProjectGrid({
  canDelete = false,
  basePath,
  mode,
  onDeleted,
  projects,
  loading,
  emptyText,
}: {
  canDelete?: boolean;
  basePath: string;
  mode: ProjectApiMode;
  onDeleted: (projectId: string) => void;
  projects: ProjectResponse[];
  loading: boolean;
  emptyText: string;
}) {
  if (loading) {
    return <CardSkeleton />;
  }
  if (projects.length === 0) {
    return (
      <p className="rounded-xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
        {emptyText}
      </p>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {projects.map((project) => (
        <ProjectCard
          basePath={basePath}
          canDelete={canDelete}
          key={project.id}
          mode={mode}
          onDeleted={() => onDeleted(project.id)}
          project={project}
        />
      ))}
    </div>
  );
}

/**
 * Render the authenticated Projects landing page.
 */
export function ProjectListShell({ mode = { kind: "self" } }: { mode?: ProjectApiMode }) {
  const [operatorProjects, setOperatorProjects] = useState<ProjectResponse[]>([]);
  const [openProjects, setOpenProjects] = useState<ProjectResponse[]>([]);
  const [assignedProjects, setAssignedProjects] = useState<ProjectResponse[]>([]);
  // Server totals, kept apart from the rendered arrays. The tab badges used to
  // count the arrays, which are one page long, so an Operator with 57 Projects
  // saw a badge reading 20.
  const [operatorTotal, setOperatorTotal] = useState(0);
  const [openTotal, setOpenTotal] = useState(0);
  const [assignedTotal, setAssignedTotal] = useState(0);
  // A page per tab, not one shared counter. Keeping them apart is what lets a
  // tab change be a pure re-render: the fetch depends on these positions, so
  // moving between tabs touches no dependency and reissues no request. It also
  // means leaving a tab and coming back does not lose your place in it.
  const [pages, setPages] = useState<Record<string, number>>({
    engagements: 1,
    open: 1,
    posted: 1,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Roles are stable for the page lifetime; an empty list (token not yet hydrated)
  // falls back to showing every tab so nothing is hidden from a valid session.
  const [roles] = useState<string[]>(() => authTokenStore.getState().roles);
  const showOperator = roles.length === 0 || roles.includes("operator") || mode.kind === "org";
  const showContributor = mode.kind === "self" && (roles.length === 0 || roles.includes("contributor"));

  const tabItems = useMemo<TabItem[]>(() => {
    const items: TabItem[] = [];
    if (showContributor) {
      items.push({ id: "open", label: "Open", count: openTotal });
    }
    if (showOperator) {
      items.push({ id: "posted", label: "Posted", count: operatorTotal });
    }
    if (showContributor) {
      items.push({
        id: "engagements",
        label: "My engagements",
        count: assignedTotal,
      });
    }
    return items;
  }, [
    showContributor,
    showOperator,
    openTotal,
    operatorTotal,
    assignedTotal,
  ]);

  const requestedTab = searchParams.get("tab");
  const activeTab =
    tabItems.find((tab) => tab.id === requestedTab)?.id ??
    tabItems[0]?.id ??
    "open";

  function selectTab(id: string): void {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", id);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  const modeKind = mode.kind;
  const modeOrgId = mode.kind === "org" ? mode.orgId : undefined;
  const projectBasePath =
    mode.kind === "org"
      ? `/dashboard/organizations/${mode.orgId}/projects`
      : "/projects";

  // The footer describes the tab on screen, so every figure comes from that
  // list's own total rather than a shared counter.
  const activeTotal =
    activeTab === "posted"
      ? operatorTotal
      : activeTab === "engagements"
        ? assignedTotal
        : openTotal;
  const totalPages = Math.max(1, Math.ceil(activeTotal / PAGE_SIZE));
  const page = pages[activeTab] ?? 1;
  const rangeStart = activeTotal === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, activeTotal);

  /** Move the tab on screen to another page, leaving the other tabs alone. */
  function setActivePage(next: number): void {
    setPages((current) => ({ ...current, [activeTab]: next }));
  }

  function removeDeletedProject(projectId: string): void {
    setOperatorProjects((current) =>
      current.filter((project) => project.id !== projectId),
    );
    // The total drives the badge and the page range, so it has to follow the
    // row out rather than keep counting something that is gone.
    setOperatorTotal((current) => Math.max(0, current - 1));
  }

  useEffect(() => {
    let mounted = true;
    async function loadProjects() {
      configureBrowserClient();
      setLoading(true);
      setError(null);
      const headers = getAccessTokenHeaders();
      const roles = authTokenStore.getState().roles;
      const shouldLoadOperator = roles.length === 0 || roles.includes("operator") || modeKind === "org";
      const shouldLoadContributor =
        modeKind === "self" && (roles.length === 0 || roles.includes("contributor"));
      // Only the tab on screen is paged; the other two are fetched at page 1
      // purely so their badges can show a total.
      const pageFor = (tab: string) => pages[tab] ?? 1;
      const [operatorResult, contributorResult, assignedResult] =
        await Promise.all([
          shouldLoadOperator
            ? modeKind === "org" && modeOrgId !== undefined
              ? listOrgProjects({
                  headers,
                  path: { org_id: modeOrgId },
                  query: { page: pageFor("posted"), page_size: PAGE_SIZE },
                })
              : listProjects({
                  headers,
                  query: {
                    page: pageFor("posted"),
                    page_size: PAGE_SIZE,
                    role: "operator",
                  },
                })
            : Promise.resolve(null),
          shouldLoadContributor
            ? listProjects({
                headers,
                query: {
                  page: pageFor("open"),
                  page_size: PAGE_SIZE,
                  role: "contributor",
                  scope: "open",
                },
              })
            : Promise.resolve(null),
          shouldLoadContributor
            ? listProjects({
                headers,
                query: {
                  page: pageFor("engagements"),
                  page_size: PAGE_SIZE,
                  role: "contributor",
                  scope: "assigned",
                },
              })
            : Promise.resolve(null),
        ]);
      if (!mounted) {
        return;
      }
      if (operatorResult?.response.ok && operatorResult.data) {
        setOperatorProjects(operatorResult.data.projects);
        setOperatorTotal(operatorResult.data.total ?? 0);
      }
      if (contributorResult?.response.ok && contributorResult.data) {
        setOpenProjects(contributorResult.data.projects);
        setOpenTotal(contributorResult.data.total ?? 0);
      }
      if (assignedResult?.response.ok && assignedResult.data) {
        setAssignedProjects(assignedResult.data.projects);
        setAssignedTotal(assignedResult.data.total ?? 0);
      }
      const failedResults = [
        operatorResult,
        contributorResult,
        assignedResult,
      ].filter((result) => result && !result.response.ok);
      const successfulResults = [
        operatorResult,
        contributorResult,
        assignedResult,
      ].filter((result) => result?.response.ok);
      if (failedResults.length > 0 && successfulResults.length === 0) {
        setError(describeGeneratedError(failedResults[0]?.error));
      }
      setLoading(false);
    }
    void loadProjects();
    return () => {
      mounted = false;
    };
    // Deliberately not keyed on `activeTab`: switching tabs must not refetch.
  }, [modeKind, modeOrgId, pages]);

  return (
    <section className="mx-auto grid max-w-6xl gap-8 px-4 py-10 md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Projects
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Commission and deliver custom work
          </h1>
        </div>
        {/* Posting is Operator-gated but the route guard admits Contributors,
            so an unconditional link walked them through the whole form only to
            lose it to a 403 on submit. Point them at the role instead — a
            Contributor who wants to commission work is a customer, not an
            error. */}
        <Link
          className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
          href={
            !showOperator
              ? `/settings/roles?next=${encodeURIComponent(`${projectBasePath}/new`)}`
              : mode.kind === "org"
                ? `${projectBasePath}?view=create`
                : `${projectBasePath}/new`
          }
        >
          {showOperator ? "Post project" : "Become an Operator to post"}
        </Link>
      </div>

      {error ? (
        <div className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-4 text-sm text-[#DC2626]">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4">
        {tabItems.length > 1 ? (
          <Tabs
            activeId={activeTab}
            label="Projects"
            onChange={selectTab}
            tabs={tabItems}
          />
        ) : null}
        <div
          aria-labelledby={tabId(activeTab)}
          className="outline-none"
          id={tabPanelId(activeTab)}
          role="tabpanel"
          tabIndex={0}
        >
          {activeTab === "open" ? (
            <ProjectGrid
              basePath={projectBasePath}
              emptyText="No open Projects available right now. Check back soon."
              loading={loading}
              mode={mode}
              onDeleted={removeDeletedProject}
              projects={openProjects}
            />
          ) : null}
          {activeTab === "posted" ? (
            <ProjectGrid
              basePath={projectBasePath}
              canDelete
              emptyText="No posted Projects yet. Post one to start commissioning work."
              loading={loading}
              mode={mode}
              onDeleted={removeDeletedProject}
              projects={operatorProjects}
            />
          ) : null}
          {activeTab === "engagements" ? (
            <ProjectGrid
              basePath={projectBasePath}
              emptyText="No active engagements yet. Accepted proposals appear here."
              loading={loading}
              mode={mode}
              onDeleted={removeDeletedProject}
              projects={assignedProjects}
            />
          ) : null}
          {activeTotal > 0 ? (
            <nav
              aria-label="Project list pages"
              className="mt-4 flex flex-col gap-3 rounded-xl border border-border-default bg-surface-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <p className="text-sm text-foreground-muted">
                Showing{" "}
                <span className="font-semibold text-foreground">
                  {rangeStart}
                </span>{" "}
                to{" "}
                <span className="font-semibold text-foreground">{rangeEnd}</span>{" "}
                of{" "}
                <span className="font-semibold text-foreground">
                  {activeTotal}
                </span>
              </p>
              <div className="flex gap-2">
                <button
                  className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={page <= 1 || loading}
                  onClick={() => setActivePage(Math.max(1, page - 1))}
                  type="button"
                >
                  Previous
                </button>
                <button
                  className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={page >= totalPages || loading}
                  onClick={() => setActivePage(page + 1)}
                  type="button"
                >
                  Next
                </button>
              </div>
            </nav>
          ) : null}
        </div>
      </div>
    </section>
  );
}
