"use client";

/**
 * Featured spotlights editor.
 *
 * Controlled, replace-all editor for the profile's "Featured" section (flagship
 * framework, case study, or milestone). Up to three cards; the parent persists
 * the array via PATCH /profiles/me.
 */
import { Button } from "@/components/ui/button";
import type { ProfileFeatured } from "@/lib/generated/types.gen";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20";
const LABEL_CLASS =
  "block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

const MAX_FEATURED = 3;

type FeaturedEditorProps = {
  value: ProfileFeatured[];
  onChange: (next: ProfileFeatured[]) => void;
};

/**
 * Render the editable featured spotlights list.
 *
 * @param props - The current entries and a change handler.
 */
export function FeaturedEditor({ value, onChange }: FeaturedEditorProps) {
  /**
   * Patch one entry by index.
   *
   * @param index - Entry position.
   * @param patch - Partial fields to merge.
   */
  function update(index: number, patch: Partial<ProfileFeatured>): void {
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  return (
    <div className="space-y-3">
      <span className={LABEL_CLASS}>Featured</span>
      {value.map((item, index) => (
        <div
          className="space-y-3 rounded-xl border border-border-default bg-surface-2/40 p-4"
          key={index}
        >
          <input
            aria-label="Featured title"
            className={FIELD_CLASS}
            maxLength={160}
            onChange={(event) => update(index, { title: event.target.value })}
            placeholder="Title (e.g. flagship framework)"
            value={item.title}
          />
          <textarea
            aria-label="Featured description"
            className={FIELD_CLASS}
            maxLength={500}
            onChange={(event) => update(index, { description: event.target.value })}
            placeholder="Short summary"
            rows={2}
            value={item.description ?? ""}
          />
          <input
            aria-label="Featured link"
            className={FIELD_CLASS}
            maxLength={2048}
            onChange={(event) => update(index, { url: event.target.value })}
            placeholder="https://… (optional)"
            value={item.url ?? ""}
          />
          <Button
            onClick={() => onChange(value.filter((_, i) => i !== index))}
            variant="secondary"
          >
            Remove
          </Button>
        </div>
      ))}
      {value.length < MAX_FEATURED ? (
        <Button
          onClick={() => onChange([...value, { title: "" }])}
          variant="secondary"
        >
          Add featured
        </Button>
      ) : null}
    </div>
  );
}
