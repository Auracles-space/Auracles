"use client";

/**
 * Social links editor.
 *
 * One URL field per allow-listed platform (the backend stores at most one link
 * per platform), so there is no add/remove — a blank field simply means "no
 * link for this platform". Only non-blank entries are emitted to the parent.
 *
 * Maps to: FR-SET-001/002.
 */
import type { SocialLink } from "@/lib/generated/types.gen";

import {
  SOCIAL_PLATFORMS,
  type SocialPlatform,
} from "@/components/modules/profiles/social-platforms";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-3 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-0";

type SocialLinksEditorProps = {
  /** The current social links (one per platform at most). */
  value: SocialLink[];
  /** Called with the next non-blank social links whenever a field changes. */
  onChange: (next: SocialLink[]) => void;
};

/**
 * Render a URL field per social platform.
 *
 * @param props - The current social links and a change handler.
 */
export function SocialLinksEditor({ value, onChange }: SocialLinksEditorProps) {
  const byPlatform = new Map(value.map((link) => [link.platform, link.url]));

  function setUrl(platform: SocialPlatform, url: string): void {
    const next = new Map(byPlatform);
    next.set(platform, url);
    onChange(
      SOCIAL_PLATFORMS.flatMap(({ platform: key }) => {
        const val = next.get(key);
        // We do not trim here, to allow the user to type trailing spaces if they need to,
        // empty string values are filtered out.
        return val ? [{ platform: key, url: val }] : [];
      }),
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {SOCIAL_PLATFORMS.map(({ platform, label, placeholder, Icon }) => (
        <div className="flex items-center gap-3" key={platform}>
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-default bg-surface-2 text-foreground-muted"
            title={label}
          >
            <Icon className="h-5 w-5" />
          </span>
          <input
            aria-label={`${label} URL`}
            className={FIELD_CLASS}
            inputMode="url"
            maxLength={2048}
            onChange={(event) => setUrl(platform, event.target.value)}
            placeholder={placeholder}
            value={byPlatform.get(platform) ?? ""}
          />
        </div>
      ))}
    </div>
  );
}
