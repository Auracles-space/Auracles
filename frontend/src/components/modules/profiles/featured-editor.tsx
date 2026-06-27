"use client";

/**
 * Featured spotlights editor.
 *
 * Controlled, replace-all editor for the profile's "Featured" section. Each card
 * is either a pinned published Framework (chosen from the owner's own) or a
 * free-form entry (title + description + link). Up to three; the parent persists
 * the array via PATCH /profiles/me.
 */
import { Button } from "@/components/ui/button";
import type { ProfileFeatured } from "@/lib/generated/types.gen";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20";
const LABEL_CLASS =
  "block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

const MAX_FEATURED = 3;

type FrameworkOption = {
  id: string;
  title: string;
};

type FeaturedEditorProps = {
  value: ProfileFeatured[];
  onChange: (next: ProfileFeatured[]) => void;
  /** The owner's published Frameworks, offered in the pin picker. */
  frameworks: FrameworkOption[];
};

/**
 * Render the editable featured spotlights list.
 *
 * @param props - Current entries, a change handler, and the owner's published
 *   Frameworks for the pin picker.
 */
export function FeaturedEditor({
  value,
  onChange,
  frameworks,
}: FeaturedEditorProps) {
  /**
   * Patch one entry by index.
   *
   * @param index - Entry position.
   * @param patch - Partial fields to merge.
   */
  function update(index: number, patch: Partial<ProfileFeatured>): void {
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  // Frameworks already pinned in any card, so each picker can hide the ones
  // taken elsewhere and never feature the same framework twice.
  const pinnedElsewhere = new Set(
    value.map((item) => item.framework_id).filter(Boolean) as string[],
  );

  return (
    <div className="space-y-3">
      <span className={LABEL_CLASS}>Featured</span>
      {value.map((item, index) => {
        const isPinned = Boolean(item.framework_id);
        const options = frameworks.filter(
          (framework) =>
            framework.id === item.framework_id ||
            !pinnedElsewhere.has(framework.id),
        );
        return (
          <div
            className="space-y-3 rounded-xl border border-border-default bg-surface-2/40 p-4"
            key={index}
          >
            {frameworks.length > 0 ? (
              <div className="space-y-1">
                <span className={LABEL_CLASS}>Pin a framework</span>
                <select
                  aria-label="Pin a framework"
                  className={FIELD_CLASS}
                  onChange={(event) =>
                    update(index, {
                      framework_id: event.target.value || null,
                      // Clear free-form title when a framework is pinned.
                      title: event.target.value ? null : item.title,
                    })
                  }
                  value={item.framework_id ?? ""}
                >
                  <option value="">None — free-form spotlight</option>
                  {options.map((framework) => (
                    <option key={framework.id} value={framework.id}>
                      {framework.title}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {!isPinned ? (
              <>
                <input
                  aria-label="Featured title"
                  className={FIELD_CLASS}
                  maxLength={160}
                  onChange={(event) => update(index, { title: event.target.value })}
                  placeholder="Title (e.g. case study, milestone)"
                  value={item.title ?? ""}
                />
                <textarea
                  aria-label="Featured description"
                  className={FIELD_CLASS}
                  maxLength={500}
                  onChange={(event) =>
                    update(index, { description: event.target.value })
                  }
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
              </>
            ) : (
              <p className="text-sm text-foreground-muted">
                Showing this framework&apos;s live card.
              </p>
            )}

            <Button
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              variant="secondary"
            >
              Remove
            </Button>
          </div>
        );
      })}
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
