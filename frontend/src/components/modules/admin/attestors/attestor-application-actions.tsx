"use client";

/**
 * Decision controls for one attestor application.
 *
 * Renders only the actions the gates allow: start the trial (with a fixture
 * picker), approve, send back for information (with one-click presets), or
 * reject with a reason. The API calls live in the parent hook so this stays a
 * form; approve and reject require an open step-up window server-side.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { CalibrationFixtureItem } from "@/lib/generated/types.gen";

import type { ApplicationGates } from "./attestor-gates";

/** One-click feedback for the most common send-back reasons. */
export const NEEDS_INFO_PRESETS: { label: string; text: string }[] = [
  {
    label: "Payout account",
    text: "Please connect a payout account under the Payout Account step so we can release attestation earnings, then resubmit.",
  },
  {
    label: "Tax documents",
    text: "Please upload the tax documents required for payouts under the Tax Documents step, then resubmit.",
  },
  {
    label: "Calibration trial",
    text: "Please nominate a member to complete the calibration trial before resubmitting.",
  },
];

type FeedbackMode = "needs_info" | "reject";

type AttestorApplicationActionsProps = {
  orgName: string;
  gates: ApplicationGates;
  fixtures: CalibrationFixtureItem[];
  busy: boolean;
  onStartTrial: (fixtureId: string) => void;
  onApprove: () => void;
  onNeedsInfo: (feedback: string) => void;
  onReject: (feedback: string) => void;
};

/**
 * Render the gated decision buttons and their inline forms.
 *
 * @param props - Gates, fixtures, and action callbacks.
 */
export function AttestorApplicationActions({
  orgName,
  gates,
  fixtures,
  busy,
  onStartTrial,
  onApprove,
  onNeedsInfo,
  onReject,
}: AttestorApplicationActionsProps) {
  const [fixtureId, setFixtureId] = useState("");
  const [mode, setMode] = useState<FeedbackMode | null>(null);
  const [feedback, setFeedback] = useState("");

  function openMode(next: FeedbackMode) {
    setMode((current) => (current === next ? null : next));
    setFeedback("");
  }

  function submitFeedback() {
    const trimmed = feedback.trim();
    if (!trimmed || !mode) {
      return;
    }
    if (mode === "needs_info") {
      onNeedsInfo(trimmed);
    } else {
      onReject(trimmed);
    }
    setMode(null);
    setFeedback("");
  }

  if (gates.decided) {
    return null;
  }

  return (
    <div className="grid gap-3">
      {gates.nextStep ? (
        <p className="text-sm font-medium text-foreground">{gates.nextStep}</p>
      ) : null}

      {gates.canStartTrial ? (
        <label className="grid gap-2 text-sm font-medium text-foreground sm:max-w-md">
          Calibration fixture for {orgName}
          <Select
            aria-label={`Calibration fixture for ${orgName}`}
            onChange={(event) => setFixtureId(event.target.value)}
            value={fixtureId}
          >
            <option value="">Select a fixture</option>
            {fixtures.map((fixture) => (
              <option key={fixture.id} value={fixture.id}>
                {fixture.title} ({fixture.review_type})
              </option>
            ))}
          </Select>
        </label>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {!gates.kybDone ? (
          <a
            className="inline-flex min-h-12 items-center rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
            href="/admin/organizations"
          >
            Verify in Organizations
          </a>
        ) : null}
        <Button
          disabled={busy || !gates.canStartTrial || !fixtureId}
          onClick={() => onStartTrial(fixtureId)}
        >
          Start trial
        </Button>
        <Button disabled={busy || !gates.canApprove} onClick={onApprove}>
          Approve
        </Button>
        <Button
          disabled={busy || !gates.canNeedsInfo}
          onClick={() => openMode("needs_info")}
          variant="secondary"
        >
          Needs info
        </Button>
        <Button
          disabled={busy || !gates.canReject}
          onClick={() => openMode("reject")}
          variant="destructive"
        >
          Reject
        </Button>
      </div>

      {mode ? (
        <div className="grid gap-3 rounded-xl border border-border-default bg-surface-2 p-4">
          {mode === "needs_info" ? (
            <div className="flex flex-wrap gap-2">
              {NEEDS_INFO_PRESETS.map((preset) => (
                <button
                  className="min-h-11 rounded-xl border border-border-default bg-surface-1 px-3 text-xs font-semibold text-foreground-muted transition hover:border-accent hover:text-foreground"
                  key={preset.label}
                  onClick={() => setFeedback(preset.text)}
                  type="button"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          ) : null}
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            {mode === "reject" ? "Rejection reason" : "What the organization must add"}
            <Textarea
              className="min-h-24"
              onChange={(event) => setFeedback(event.target.value)}
              value={feedback}
            />
          </label>
          <div>
            <Button
              disabled={busy || !feedback.trim()}
              onClick={submitFeedback}
              variant={mode === "reject" ? "destructive" : "primary"}
            >
              {mode === "reject" ? "Confirm reject" : "Confirm needs info"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
