/**
 * The requestor's brief, shown to the reviewing attestor.
 *
 * The brief is what the requestor actually wants judged, and until now it was
 * only visible to them: the reviewer opened a workspace full of files with no
 * statement of intent. Rendered read-only, and skipped entirely when the
 * request carries no brief (older requests, non-framework targets).
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */
import { ExpandableText } from "@/components/ui/expandable-text";

/** Brief fields worth showing, in the order the reviewer needs them. */
const BRIEF_FIELDS: { key: string; label: string }[] = [
  { key: "what_it_does", label: "What it does" },
  { key: "use_case", label: "Use case" },
  { key: "desired_outcome", label: "Desired outcome" },
];

/**
 * Read one brief key as trimmed text, ignoring non-string values.
 *
 * @param brief - Raw brief object from the API (untyped JSON).
 * @param key - Field to read.
 */
function readBriefField(
  brief: Record<string, unknown>,
  key: string,
): string | null {
  const value = brief[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

type ReviewBriefCardProps = {
  /** Raw brief object from the attestation response. */
  brief?: Record<string, unknown> | null;
};

/**
 * Render the requestor's brief as a labelled summary card.
 *
 * @param props - The raw brief object, when the request has one.
 */
export function ReviewBriefCard({ brief }: ReviewBriefCardProps) {
  if (!brief) {
    return null;
  }
  const entries = BRIEF_FIELDS.map((field) => ({
    label: field.label,
    value: readBriefField(brief, field.key),
  })).filter((entry) => entry.value);

  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-base font-bold text-foreground">
        What the requestor asked for
      </h3>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        {entries.map((entry) => (
          <div className="min-w-0 rounded-xl bg-surface-2 p-4" key={entry.label}>
            <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              {entry.label}
            </dt>
            <dd className="mt-1">
              <ExpandableText
                className="text-sm leading-6 text-foreground"
                text={entry.value ?? ""}
              />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
