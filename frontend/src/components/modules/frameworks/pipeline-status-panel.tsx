/**
 * Contributor pipeline status panel.
 *
 * Converts backend Artifact status fields into human-readable gate checks for
 * publish readiness. The backend remains the source of truth for enforcement.
 */
import type { ArtifactResponse, FrameworkResponse } from "@/lib/generated/types.gen";

type PipelineStatusPanelProps = {
  artifacts: ArtifactResponse[];
  frameworkStatus: FrameworkResponse["status"];
};

type PipelineCheck = {
  description: string;
  label: string;
  state: "pass" | "pending" | "fail";
  value: string;
};

/**
 * Build the pipeline status matrix shown to Contributors.
 *
 * @param artifacts - Artifacts currently attached to the Framework.
 * @param frameworkStatus - Current Framework workflow status.
 * @returns Ordered pipeline checks.
 */
export function buildPipelineChecks(
  artifacts: ArtifactResponse[],
  frameworkStatus: FrameworkResponse["status"],
): PipelineCheck[] {
  const hasArtifacts = artifacts.length > 0;
  const hasInfected = artifacts.some((artifact) => artifact.scan_status === "infected");
  const hasScanError = artifacts.some((artifact) => artifact.scan_status === "error");
  const allClean = hasArtifacts && artifacts.every((artifact) => artifact.scan_status === "clean");
  const anyPiiReview = artifacts.some((artifact) => artifact.pii_review_needed);
  const allProcessed =
    hasArtifacts &&
    artifacts.every((artifact) => artifact.processing_status === "processed");
  const anyRarityFail = artifacts.some(
    (artifact) => artifact.processing_status === "flagged_rarity",
  );
  const allGreen = frameworkStatus === "pipeline_passed";

  return [
    {
      description: hasArtifacts
        ? "Every artifact must scan clean before publish."
        : "Upload at least one artifact to start scanning.",
      label: "Virus scan",
      state: allClean ? "pass" : hasInfected || hasScanError ? "fail" : "pending",
      value: allClean ? "Clean" : hasInfected ? "Infected" : "Pending",
    },
    {
      description: anyPiiReview
        ? "Replace or resolve the flagged artifact before publishing."
        : "PII checks protect users from publishing sensitive data.",
      label: "PII review",
      state: anyPiiReview ? "fail" : allProcessed || allGreen ? "pass" : "pending",
      value: anyPiiReview ? "Review required" : allProcessed || allGreen ? "No review needed" : "Pending",
    },
    {
      description: anyRarityFail
        ? "External rarity concerns need acknowledgement before publish."
        : "Rarity checks reduce low-originality submissions.",
      label: "Rarity",
      state: anyRarityFail ? "fail" : allProcessed || allGreen ? "pass" : "pending",
      value: anyRarityFail ? "Soft fail" : allProcessed || allGreen ? "Passed" : "Pending",
    },
  ];
}

/**
 * Render publish-gate checks for one Framework.
 *
 * @param props - Framework status and attached artifacts.
 */
export function PipelineStatusPanel({
  artifacts,
  frameworkStatus,
}: PipelineStatusPanelProps) {
  const checks = buildPipelineChecks(artifacts, frameworkStatus);

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 sm:p-8 shadow-sm">
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-heading text-lg font-bold text-foreground">
            Pipeline status
          </h2>
          <p className="text-sm text-foreground-muted">
            Publish is available only after the backend gate passes.
          </p>
        </div>
        <span className="w-fit rounded-lg border border-border-default px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {frameworkStatus.replaceAll("_", " ")}
        </span>
      </div>
      <div className="grid gap-4">
        {checks.map((check) => (
          <div
            className="rounded-xl border border-border-default bg-background p-5 shadow-[0_2px_8px_-2px_rgba(0,0,0,0.05)] transition-all hover:shadow-[0_4px_12px_-2px_rgba(0,0,0,0.08)]"
            key={check.label}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold text-foreground">{check.label}</p>
              <span className={badgeClass(check.state)}>{check.value}</span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
              {check.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * Return Brand Book semantic status badge classes.
 *
 * @param state - Pipeline check state.
 */
function badgeClass(state: PipelineCheck["state"]): string {
  if (state === "pass") {
    return "rounded-lg border border-success/20 bg-success/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-success";
  }
  if (state === "fail") {
    return "rounded-lg border border-error/20 bg-error/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-error";
  }
  return "rounded-lg border border-warning/20 bg-warning/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-warning";
}
