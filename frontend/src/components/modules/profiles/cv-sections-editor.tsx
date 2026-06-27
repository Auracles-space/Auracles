"use client";

/**
 * Experience and education editors.
 *
 * Controlled list editors for the profile's CV sections. Each is replace-all:
 * the parent holds the array and persists it via PATCH /profiles/me. Kept in a
 * dedicated file so the main profile editor stays readable.
 */
import { Button } from "@/components/ui/button";
import type {
  ProfileEducation,
  ProfileExperience,
} from "@/lib/generated/types.gen";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-0";
const LABEL_CLASS =
  "block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

const MAX_EXPERIENCE = 20;
const MAX_EDUCATION = 15;

type ExperienceEditorProps = {
  value: ProfileExperience[];
  onChange: (next: ProfileExperience[]) => void;
};

/**
 * Render the editable experience timeline.
 *
 * @param props - The current entries and a change handler.
 */
export function ExperienceEditor({ value, onChange }: ExperienceEditorProps) {
  /**
   * Patch one entry by index.
   *
   * @param index - Entry position.
   * @param patch - Partial fields to merge.
   */
  function update(index: number, patch: Partial<ProfileExperience>): void {
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  return (
    <div className="space-y-3">
      <span className={LABEL_CLASS}>Experience</span>
      {value.map((item, index) => (
        <div
          className="space-y-3 rounded-xl border border-border-default bg-surface-2/40 p-4"
          key={index}
        >
          <div className="flex items-center justify-between border-b border-border-default pb-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">Position #{index + 1}</span>
            <button
              aria-label="Remove experience"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              type="button"
              className="flex h-10 w-10 sm:h-8 sm:w-8 items-center justify-center rounded-lg border border-border-default bg-surface-1 text-foreground-muted hover:border-error/30 hover:bg-error/5 hover:text-error transition-all cursor-pointer"
            >
              <svg className="h-5 w-5 sm:h-4 sm:w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              aria-label="Title"
              className={FIELD_CLASS}
              maxLength={160}
              onChange={(event) => update(index, { title: event.target.value })}
              placeholder="Title"
              value={item.title}
            />
            <input
              aria-label="Company"
              className={FIELD_CLASS}
              maxLength={160}
              onChange={(event) => update(index, { company: event.target.value })}
              placeholder="Company"
              value={item.company}
            />
            <input
              aria-label="Start"
              className={FIELD_CLASS}
              maxLength={40}
              onChange={(event) => update(index, { start: event.target.value })}
              placeholder="Start (e.g. 2021)"
              value={item.start ?? ""}
            />
            <input
              aria-label="End"
              className={FIELD_CLASS}
              disabled={item.current ?? false}
              maxLength={40}
              onChange={(event) => update(index, { end: event.target.value })}
              placeholder="End (e.g. 2024)"
              value={item.current ? "" : (item.end ?? "")}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-foreground-muted">
            <input
              checked={item.current ?? false}
              className="h-4 w-4 rounded border-border-default bg-surface-1 text-accent focus:ring-0 focus:ring-transparent cursor-pointer accent-accent"
              onChange={(event) => update(index, { current: event.target.checked })}
              type="checkbox"
            />
            I currently work here
          </label>
          <textarea
            aria-label="Description"
            className={FIELD_CLASS}
            maxLength={2000}
            onChange={(event) => update(index, { description: event.target.value })}
            placeholder="What you did"
            rows={3}
            value={item.description ?? ""}
          />
        </div>
      ))}
      {value.length < MAX_EXPERIENCE ? (
        <Button
          onClick={() => onChange([...value, { title: "", company: "" }])}
          variant="secondary"
          className="w-full flex items-center justify-center gap-2"
        >
          <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add experience
        </Button>
      ) : null}
    </div>
  );
}

type EducationEditorProps = {
  value: ProfileEducation[];
  onChange: (next: ProfileEducation[]) => void;
};

/**
 * Render the editable education list.
 *
 * @param props - The current entries and a change handler.
 */
export function EducationEditor({ value, onChange }: EducationEditorProps) {
  /**
   * Patch one entry by index.
   *
   * @param index - Entry position.
   * @param patch - Partial fields to merge.
   */
  function update(index: number, patch: Partial<ProfileEducation>): void {
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  /**
   * Parse a year input into a number or null.
   *
   * @param raw - The raw input value.
   */
  function toYear(raw: string): number | null {
    const trimmed = raw.trim();
    if (!trimmed) {
      return null;
    }
    const year = Number(trimmed);
    return Number.isInteger(year) ? year : null;
  }

  return (
    <div className="space-y-3">
      <span className={LABEL_CLASS}>Education</span>
      {value.map((item, index) => (
        <div
          className="space-y-3 rounded-xl border border-border-default bg-surface-2/40 p-4"
          key={index}
        >
          <div className="flex items-center justify-between border-b border-border-default pb-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">Education #{index + 1}</span>
            <button
              aria-label="Remove education"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              type="button"
              className="flex h-10 w-10 sm:h-8 sm:w-8 items-center justify-center rounded-lg border border-border-default bg-surface-1 text-foreground-muted hover:border-error/30 hover:bg-error/5 hover:text-error transition-all cursor-pointer"
            >
              <svg className="h-5 w-5 sm:h-4 sm:w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
          <input
            aria-label="School"
            className={FIELD_CLASS}
            maxLength={160}
            onChange={(event) => update(index, { school: event.target.value })}
            placeholder="School"
            value={item.school}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              aria-label="Degree"
              className={FIELD_CLASS}
              maxLength={160}
              onChange={(event) => update(index, { degree: event.target.value })}
              placeholder="Degree"
              value={item.degree ?? ""}
            />
            <input
              aria-label="Field of study"
              className={FIELD_CLASS}
              maxLength={160}
              onChange={(event) => update(index, { field: event.target.value })}
              placeholder="Field of study"
              value={item.field ?? ""}
            />
            <input
              aria-label="Start year"
              className={FIELD_CLASS}
              inputMode="numeric"
              onChange={(event) =>
                update(index, { start_year: toYear(event.target.value) })
              }
              placeholder="Start year"
              value={item.start_year ?? ""}
            />
            <input
              aria-label="End year"
              className={FIELD_CLASS}
              inputMode="numeric"
              onChange={(event) =>
                update(index, { end_year: toYear(event.target.value) })
              }
              placeholder="End year"
              value={item.end_year ?? ""}
            />
          </div>
        </div>
      ))}
      {value.length < MAX_EDUCATION ? (
        <Button
          onClick={() => onChange([...value, { school: "" }])}
          variant="secondary"
          className="w-full flex items-center justify-center gap-2"
        >
          <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add education
        </Button>
      ) : null}
    </div>
  );
}
