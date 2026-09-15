"use client";

/**
 * The Attestation request form: target framework, review type, and the brief
 * the attestor cohort reads before taking the work.
 *
 * The framework is either picked from the requestor's own published work or
 * pinned by the `target` link that opened the form — including a framework
 * someone else owns, which routes through owner consent before any fee.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useId, useState } from "react";

import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  CHECKOUT_COUNTRIES,
  defaultBillingCountry,
} from "@/lib/marketplace/countries";
import { JURISDICTION_OPTIONS } from "@/lib/marketplace/taxonomy";
import type { FrameworkListItem } from "@/lib/generated/types.gen";
import { isNonEmpty } from "@/lib/forms/validators";
import {
  REVIEW_TYPE_LABELS,
  inFlightAttestationsFor,
  type InFlightCandidate,
} from "@/lib/attestation/in-flight";

/** Server cap on each free-text brief field (`AttestationBrief` in the API). */
export const BRIEF_FIELD_MAX_LENGTH = 2000;

export type ReviewType = "" | "quality" | "compliance" | "expert" | "provenance";

export type AttestationRequestDraft = {
  targetId: string;
  reviewType: ReviewType;
  brief: {
    what_it_does: string;
    use_case: string;
    jurisdiction: string;
    focus_areas: string;
    desired_outcome: string;
  };
  country: string;
};

type AttestationRequestFormProps = {
  /** The framework fixed by the link that opened the form, if any. */
  pinned: { id: string; title: string; external: boolean } | null;
  /** The requestor's own frameworks, offered when nothing is pinned. */
  myFrameworks: FrameworkListItem[];
  /**
   * The requestor's existing requests; a review type already in progress for
   * the chosen framework is disabled, because the server refuses a duplicate.
   */
  inFlight?: InFlightCandidate[];
  /** Whether the collapsible block starts open. */
  defaultOpen: boolean;
  /** Whether a request is in flight. */
  submitting: boolean;
  /**
   * Send the request.
   *
   * @returns True when the fields should be cleared (the request landed and
   *   the browser is staying on this page).
   */
  onSubmit: (draft: AttestationRequestDraft) => Promise<boolean>;
};

/**
 * Render the collapsible Attestation request form.
 *
 * @param props - Pinned framework, own frameworks, open state, and submit.
 */
export function AttestationRequestForm({
  pinned,
  myFrameworks,
  inFlight = [],
  defaultOpen,
  submitting,
  onSubmit,
}: AttestationRequestFormProps) {
  const [targetId, setTargetId] = useState(pinned?.id ?? "");
  const [reviewType, setReviewType] = useState<ReviewType>("");
  const [whatItDoes, setWhatItDoes] = useState("");
  const [useCase, setUseCase] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [focusAreas, setFocusAreas] = useState("");
  const [desiredOutcome, setDesiredOutcome] = useState("");
  // Billing country drives the payment rail (Nigeria pays the fee through
  // Paystack hosted checkout), so it is shown and editable, never inferred.
  const [country, setCountry] = useState(defaultBillingCountry);

  const effectiveTarget = pinned?.id ?? targetId;
  const busyReviewTypes = new Set(
    inFlightAttestationsFor(inFlight, effectiveTarget).map(
      (attestation) => attestation.review_type,
    ),
  );
  // Attestation is framework-only today; the request always targets a Framework
  // and the backend requires a review type plus a fully-populated brief.
  const canRequest =
    isNonEmpty(effectiveTarget) &&
    isNonEmpty(reviewType) &&
    isNonEmpty(whatItDoes) &&
    isNonEmpty(useCase) &&
    isNonEmpty(jurisdiction) &&
    isNonEmpty(focusAreas) &&
    isNonEmpty(desiredOutcome);

  /**
   * Reset every field the requestor filled.
   *
   * A pinned framework came from the link that opened this form; clearing it
   * would leave the requestor with no picker and no target.
   */
  function clearFields() {
    setTargetId(pinned?.id ?? "");
    setReviewType("");
    setWhatItDoes("");
    setUseCase("");
    setJurisdiction("");
    setFocusAreas("");
    setDesiredOutcome("");
  }

  /** Hand the completed draft to the panel, then clear on its say-so. */
  async function handleSubmit() {
    const shouldClear = await onSubmit({
      targetId: effectiveTarget,
      reviewType,
      brief: {
        what_it_does: whatItDoes,
        use_case: useCase,
        jurisdiction,
        focus_areas: focusAreas,
        desired_outcome: desiredOutcome,
      },
      country,
    });
    if (shouldClear) {
      clearFields();
    }
  }

  return (
    <details
      className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm"
      open={defaultOpen}
    >
      <summary className="cursor-pointer font-heading text-xl font-bold text-foreground">
        {pinned ? "Request an attestation" : "Request Attestation"}
      </summary>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {pinned ? (
          <div className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Framework</span>
            <p className="rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm font-semibold text-foreground">
              {pinned.title}
            </p>
            {pinned.external ? (
              <p className="text-xs font-normal leading-5 text-foreground-muted">
                The framework owner must approve this request before you pay.
              </p>
            ) : null}
          </div>
        ) : (
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>
              Framework <span className="text-error">*</span>
            </span>
            <Select
              onChange={(event) => setTargetId(event.target.value)}
              value={targetId}
            >
              <option value="">Select a framework</option>
              {myFrameworks.map((framework) => (
                <option key={framework.id} value={framework.id}>
                  {framework.title}
                </option>
              ))}
            </Select>
          </label>
        )}
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          <span>
            Review type <span className="text-error">*</span>
          </span>
          <Select
            onChange={(event) =>
              setReviewType(event.target.value as ReviewType)
            }
            value={reviewType}
          >
            <option value="">Select a review type</option>
            {Object.entries(REVIEW_TYPE_LABELS).map(([value, label]) => (
              <option disabled={busyReviewTypes.has(value)} key={value} value={value}>
                {busyReviewTypes.has(value) ? `${label} (review in progress)` : label}
              </option>
            ))}
          </Select>
        </label>
      </div>

      <p className="mt-6 text-sm font-semibold text-foreground">Review brief</p>
      <p className="mt-1 text-sm text-foreground-muted">
        The attestor cohort sees this brief when deciding whether to take the
        review.
      </p>
      <div className="mt-3 grid gap-4">
        <BriefTextField
          label="What it does"
          onChange={setWhatItDoes}
          placeholder="What the framework does and the problem it solves."
          value={whatItDoes}
        />
        <BriefTextField
          label="Use case"
          onChange={setUseCase}
          placeholder="Who uses it and in what situation."
          value={useCase}
        />
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          <span>
            Jurisdiction <span className="text-error">*</span>
          </span>
          <Select
            onChange={(event) => setJurisdiction(event.target.value)}
            value={jurisdiction}
          >
            <option value="">Select a jurisdiction</option>
            {JURISDICTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </label>
        <BriefTextField
          label="Focus areas"
          onChange={setFocusAreas}
          placeholder="What the review should scrutinise most."
          value={focusAreas}
        />
        <BriefTextField
          label="Desired outcome"
          onChange={setDesiredOutcome}
          placeholder="What a successful attestation looks like for you."
          value={desiredOutcome}
        />
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          <span>Billing country</span>
          <Select
            disabled={submitting}
            onChange={(event) => setCountry(event.target.value)}
            value={country}
          >
            {CHECKOUT_COUNTRIES.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </Select>
          <span className="text-xs font-normal leading-5 text-foreground-muted">
            Determines how your fee payment is processed.
          </span>
        </label>
      </div>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <button
          className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canRequest || submitting}
          onClick={handleSubmit}
          type="button"
        >
          {submitting ? "Requesting…" : "Request attestation"}
        </button>
        <button
          className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={clearFields}
          type="button"
        >
          Clear form
        </button>
      </div>
    </details>
  );
}

type BriefTextFieldProps = {
  /** Visible, required field label. */
  label: string;
  /** Current value. */
  value: string;
  /** Receive the new value. */
  onChange: (value: string) => void;
  /** Hint shown while empty. */
  placeholder: string;
};

/**
 * A required brief textarea capped at the server limit, with a live counter
 * so the requestor sees the cap before a submit is refused.
 *
 * @param props - Label, value, change handler, and placeholder.
 */
function BriefTextField({ label, value, onChange, placeholder }: BriefTextFieldProps) {
  const counterId = useId();
  return (
    <div className="grid gap-2">
      <label className="grid gap-2 text-sm font-semibold text-foreground">
        <span>
          {label} <span className="text-error">*</span>
        </span>
        <Textarea
          aria-describedby={counterId}
          maxLength={BRIEF_FIELD_MAX_LENGTH}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          value={value}
        />
      </label>
      <p className="text-right text-xs text-foreground-muted" id={counterId}>
        {value.length} / {BRIEF_FIELD_MAX_LENGTH}
      </p>
    </div>
  );
}
