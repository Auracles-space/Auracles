"use client";

/**
 * Authenticated Projects landing shell.
 *
 * Operators see their posted Projects. Contributors see the open Projects they
 * can bid on plus "My engagements" — Projects they were assigned via an accepted
 * Proposal, which have left the open feed. All lists use the generated OpenAPI
 * client.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { authTokenStore } from "@/lib/auth/token-store";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { listProjects } from "@/lib/generated/sdk.gen";
import type { ProjectResponse } from "@/lib/generated/types.gen";

/**
 * Render status text in a compact operational label.
 */
function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

/**
 * Render one Project row.
 */
function ProjectCard({ project }: { project: ProjectResponse }) {
  return (
    <Link
      className="block rounded-xl border border-border-default bg-surface-1 p-6 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors hover:border-border-strong"
      href={`/projects/${project.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-heading text-lg font-semibold text-foreground">
            {project.title}
          </h3>
          <p className="mt-1 line-clamp-2 text-sm leading-6 text-foreground-muted">
            {project.description}
          </p>
        </div>
        <span className="rounded-md border border-[#2563EB]/30 bg-[#2563EB]/10 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-[#2563EB]">
          {statusLabel(project.status)}
        </span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm text-foreground-muted sm:grid-cols-3">
        <div>
          <dt className="text-xs uppercase tracking-[0.05em]">Budget</dt>
          <dd className="font-semibold text-foreground">
            ${project.budget_min} - ${project.budget_max}
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
  );
}

/**
 * Render the authenticated Projects landing page.
 */
export function ProjectListShell() {
  const [operatorProjects, setOperatorProjects] = useState<ProjectResponse[]>([]);
  const [openProjects, setOpenProjects] = useState<ProjectResponse[]>([]);
  const [assignedProjects, setAssignedProjects] = useState<ProjectResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function loadProjects() {
      configureBrowserClient();
      setLoading(true);
      setError(null);
      const headers = getAccessTokenHeaders();
      const roles = authTokenStore.getState().roles;
      const shouldLoadOperator = roles.length === 0 || roles.includes("operator");
      const shouldLoadContributor =
        roles.length === 0 || roles.includes("contributor");
      const [operatorResult, contributorResult, assignedResult] =
        await Promise.all([
          shouldLoadOperator
            ? listProjects({ headers, query: { role: "operator" } })
            : Promise.resolve(null),
          shouldLoadContributor
            ? listProjects({
                headers,
                query: { role: "contributor", scope: "open" },
              })
            : Promise.resolve(null),
          shouldLoadContributor
            ? listProjects({
                headers,
                query: { role: "contributor", scope: "assigned" },
              })
            : Promise.resolve(null),
        ]);
      if (!mounted) {
        return;
      }
      if (operatorResult?.response.ok && operatorResult.data) {
        setOperatorProjects(operatorResult.data.projects);
      }
      if (contributorResult?.response.ok && contributorResult.data) {
        setOpenProjects(contributorResult.data.projects);
      }
      if (assignedResult?.response.ok && assignedResult.data) {
        setAssignedProjects(assignedResult.data.projects);
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
  }, []);

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
        <Link
          className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
          href="/projects/new"
        >
          Post project
        </Link>
      </div>

      {error ? (
        <div className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-4 text-sm text-[#DC2626]">
          {error}
        </div>
      ) : null}

      {assignedProjects.length > 0 ? (
        <section className="grid content-start gap-3">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            My engagements
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {assignedProjects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="grid content-start gap-3">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            My posted Projects
          </h2>
          {loading ? <CardSkeleton /> : null}
          {!loading && operatorProjects.length === 0 ? (
            <p className="rounded-xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              No posted Projects yet.
            </p>
          ) : null}
          {operatorProjects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </section>

        <section className="grid content-start gap-3">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Open Projects
          </h2>
          {loading ? <CardSkeleton /> : null}
          {!loading && openProjects.length === 0 ? (
            <p className="rounded-xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              No open Projects available.
            </p>
          ) : null}
          {openProjects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </section>
      </div>
    </section>
  );
}
