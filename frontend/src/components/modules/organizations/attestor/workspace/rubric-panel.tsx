"use client";

import React, { useState } from "react";
import { upsertRubricScore } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { RUBRICS, RubricDimension } from "./rubrics";
import { Textarea } from "@/components/ui/textarea";

export interface RubricPanelProps {
  attestationId: string;
  reviewType: string;
  canWrite: boolean;
}

export function RubricPanel({
  attestationId,
  reviewType,
  canWrite,
}: RubricPanelProps) {
  const dimensions = RUBRICS[reviewType] || [];

  if (!dimensions.length) {
    return (
      <div className="text-sm text-foreground-muted">
        No rubric dimensions configured for review type: {reviewType}
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
}: {
  attestationId: string;
  dimension: RubricDimension;
  canWrite: boolean;
}) {
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
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
