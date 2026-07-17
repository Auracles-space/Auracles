"use client";

import React, { useEffect, useState } from "react";
import { upsertRubricScore, listRubricScores } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { RUBRICS, RubricDimension } from "./rubrics";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";

export interface RubricPanelProps {
  attestationId: string;
  reviewType: string;
  canWrite: boolean;
}

/** Saved score/comment for one dimension, keyed by its stable dimension key. */
type SavedScore = { score: number | null; comment: string };

export function RubricPanel({
  attestationId,
  reviewType,
  canWrite,
}: RubricPanelProps) {
  const dimensions = RUBRICS[reviewType] || [];
  const [saved, setSaved] = useState<Record<string, SavedScore>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const loadSaved = async () => {
      const res = await listRubricScores({
        path: { attestation_id: attestationId },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      if (!res.error && res.data) {
        const map: Record<string, SavedScore> = {};
        for (const item of res.data.scores) {
          map[item.dimension_key] = {
            score: item.score ?? null,
            comment: item.comment ?? "",
          };
        }
        setSaved(map);
      }
      setLoading(false);
    };
    loadSaved();
    return () => { mounted = false; };
  }, [attestationId]);

  if (!dimensions.length) {
    return (
      <div className="text-sm text-foreground-muted">
        No rubric dimensions configured for review type: {reviewType}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-foreground-muted">
        <Spinner className="h-4 w-4" /> Loading rubric...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="border-b border-border-default pb-4">
        <h2 className="text-xl font-semibold text-foreground">
          Rubric Scoring
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Evaluate the framework across {dimensions.length} dimensions. All scores
          and comments are required before submitting the final report.
        </p>
      </div>

      <div className="space-y-6">
        {dimensions.map((dim) => (
          <RubricDimensionCard
            key={dim.key}
            attestationId={attestationId}
            dimension={dim}
            canWrite={canWrite}
            initialScore={saved[dim.key]?.score ?? null}
            initialComment={saved[dim.key]?.comment ?? ""}
          />
        ))}
      </div>
    </div>
  );
}

function RubricDimensionCard({
  attestationId,
  dimension,
  canWrite,
  initialScore,
  initialComment,
}: {
  attestationId: string;
  dimension: RubricDimension;
  canWrite: boolean;
  initialScore: number | null;
  initialComment: string;
}) {
  const [score, setScore] = useState<number | null>(initialScore);
  const [comment, setComment] = useState(initialComment);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  // Persist whatever the reviewer has entered so far. The backend accepts a
  // partial rubric row (score and comment are both nullable), so a lone score
  // or a lone comment is saved immediately and survives a reload — the final
  // report submission is what enforces that every dimension is complete.
  const saveToBackend = async (data: { score: number | null; comment: string }) => {
    if (data.score === null && data.comment.trim() === "") return;
    setSaveStatus("saving");
    try {
      const res = await upsertRubricScore({
        path: {
          attestation_id: attestationId,
          dimension_key: dimension.key,
        },
        body: {
          score: data.score,
          comment: data.comment,
        },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error("Failed to save score");
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
    }
  };

  const handleScoreChange = (newScore: number) => {
    if (!canWrite) return;
    setScore(newScore);
    saveToBackend({ score: newScore, comment });
  };

  const handleCommentBlur = () => {
    if (!canWrite) return;
    saveToBackend({ score, comment });
  };

  return (
    <div className="rounded-xl border border-border-default bg-background p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-medium text-foreground">
            {dimension.label} <span className="text-error">*</span>
          </h3>
          <p className="mt-1 text-sm text-foreground-muted">
            Weight: {(dimension.weight * 100).toFixed(0)}%
          </p>
        </div>
        <div className="flex items-center space-x-2">
          {saveStatus === "saving" && <span className="text-sm text-foreground-muted">Saving...</span>}
          {saveStatus === "saved" && <span className="text-sm text-success">Saved</span>}
          {saveStatus === "error" && <span className="text-sm text-error">Error saving</span>}
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        {[1, 2, 3, 4, 5].map((val) => (
          <button
            key={val}
            disabled={!canWrite}
            onClick={() => handleScoreChange(val)}
            className={[
              "flex h-10 w-10 items-center justify-center rounded-md border text-sm font-medium transition-colors",
              score === val
                ? "border-accent bg-accent text-white"
                : "border-border-default bg-background text-foreground hover:bg-surface-elevated disabled:opacity-50"
            ].join(" ")}
          >
            {val}
          </button>
        ))}
      </div>

      <div className="mt-4">
        <label className="mb-2 block text-sm font-medium text-foreground">
          Comment <span className="text-error">*</span>
        </label>
        <Textarea
          disabled={!canWrite}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onBlur={handleCommentBlur}
          placeholder="Provide justification for this score..."
          className="h-24 resize-none"
        />
      </div>
    </div>
  );
}
