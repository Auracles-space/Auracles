/**
 * Publish-gate blocker derivation.
 *
 * Translates the artifact-level pipeline flags exposed on ArtifactResponse into
 * the hard blocks that make re-running publishing checks pointless until the
 * Contributor changes an artifact. The backend gate stays authoritative; this
 * only drives the editor's disabled state and inline guidance so the
 * Contributor is not sent to retry a check that cannot pass.
 */
import type { ArtifactResponse } from "@/lib/generated/types.gen";

/** Stable identifier for a publish blocker, used for dedupe and tests. */
export type SubmitBlockCode =
  | "virus"
  | "near_duplicate"
  | "pii"
  | "processing";

/** A single reason the framework cannot pass its publishing checks as-is. */
export type SubmitBlockReason = {
  code: SubmitBlockCode;
  label: string;
  hint: string;
};

/** Outcome of evaluating the current artifacts for hard publish blocks. */
export type SubmitBlock = {
  hardBlocked: boolean;
  reasons: SubmitBlockReason[];
};

/**
 * Ordered blocker definitions with the predicate that raises each one.
 *
 * Every blocker here requires changing or resolving an artifact — re-running
 * the checks without acting cannot clear it. Transient or acknowledge-able
 * states (scan errors, external-rarity soft fails) are intentionally excluded
 * so the retry action stays available for them.
 */
const HARD_BLOCKS: {
  code: SubmitBlockCode;
  label: string;
  hint: string;
  match: (artifact: ArtifactResponse) => boolean;
}[] = [
  {
    code: "virus",
    label: "Virus scan failed",
    hint: "Replace the infected artifact before running checks again.",
    match: (artifact) => artifact.scan_status === "infected",
  },
  {
    code: "near_duplicate",
    label: "Near-duplicate artifact",
    hint: "This file closely matches existing content. Replace it with original material.",
    match: (artifact) => Boolean(artifact.near_duplicate_blocked),
  },
  {
    code: "pii",
    label: "PII review required",
    hint: "Resolve or replace the flagged artifact before running checks again.",
    match: (artifact) => artifact.pii_review_needed,
  },
  {
    code: "processing",
    label: "Processing failed",
    hint: "Re-upload the artifact that failed to process.",
    match: (artifact) => artifact.processing_status === "failed",
  },
];

/**
 * Derive the hard publish blocks for the current artifact set.
 *
 * @param artifacts - Artifacts currently attached to the Framework.
 * @returns Whether a retry is pointless and the distinct reasons why.
 */
export function deriveSubmitBlock(artifacts: ArtifactResponse[]): SubmitBlock {
  const reasons = HARD_BLOCKS.filter((block) =>
    artifacts.some(block.match),
  ).map(({ code, label, hint }) => ({ code, label, hint }));
  return { hardBlocked: reasons.length > 0, reasons };
}
