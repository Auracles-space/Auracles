"use client";

/**
 * Required, owner-visible reason field for admin suspend / revoke dialogs.
 *
 * The text is stored on the organization row and shown to its owner, so the
 * label says so and the helper asks for plain language. The 5 to 500
 * character rule mirrors the backend `OrgStatusReasonRequest` schema; the
 * constants and `isReasonValid` live here so every dialog gates its confirm
 * button on the same check.
 *
 * Maps to: org onboarding journey design, section 2 (Admin console).
 */
import { Textarea } from "@/components/ui/textarea";

/** Minimum trimmed length the backend accepts for a reason. */
export const REASON_MIN_LENGTH = 5;
/** Maximum length the backend accepts for a reason. */
export const REASON_MAX_LENGTH = 500;

const DEFAULT_LABEL = "Reason (shown to the organization's owner)";
const HELPER_TEXT = `Explain the decision in plain language. ${REASON_MIN_LENGTH} to ${REASON_MAX_LENGTH} characters.`;

/**
 * Whether a reason, once trimmed, satisfies the backend length rule.
 *
 * @param value - Raw textarea value.
 * @returns True when the trimmed text is between the min and max length.
 */
export function isReasonValid(value: string): boolean {
  const length = value.trim().length;
  return length >= REASON_MIN_LENGTH && length <= REASON_MAX_LENGTH;
}

type ReasonFieldProps = {
  /** Element id — ties the label and helper text to the textarea. */
  id: string;
  /** Current textarea value (controlled). */
  value: string;
  /** Called with the new raw value on every edit. */
  onChange: (value: string) => void;
  /** Overrides the default owner-visible label. */
  label?: string;
  /** Disables editing, e.g. while the request is in flight. */
  disabled?: boolean;
};

/**
 * Labelled textarea with the shared reason helper copy and length cap.
 *
 * @param props - Controlled value, change handler, id, optional label/disabled.
 */
export function ReasonField({
  id,
  value,
  onChange,
  label = DEFAULT_LABEL,
  disabled = false,
}: ReasonFieldProps) {
  const helperId = `${id}-helper`;
  return (
    <div className="mt-4 flex flex-col gap-2">
      <label className="text-sm font-semibold text-foreground" htmlFor={id}>
        {label}
      </label>
      <Textarea
        aria-describedby={helperId}
        disabled={disabled}
        id={id}
        maxLength={REASON_MAX_LENGTH}
        onChange={(event) => onChange(event.target.value)}
        required
        value={value}
      />
      <div className="flex items-start justify-between gap-3 text-xs text-foreground-muted">
        <p id={helperId}>{HELPER_TEXT}</p>
        <span aria-hidden="true" className="shrink-0 tabular-nums">
          {value.length}/{REASON_MAX_LENGTH}
        </span>
      </div>
    </div>
  );
}
