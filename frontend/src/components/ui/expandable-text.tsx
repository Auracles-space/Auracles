"use client";

/**
 * Free text that stays readable at any length.
 *
 * User-written text (a review brief, up to 2,000 characters) is shown with its
 * typed line breaks, wraps unbroken strings such as URLs instead of pushing
 * past its container, and is clamped behind a Read more toggle once it is
 * long. The full text stays in the DOM while clamped, so screen readers and
 * find-in-page still reach it.
 */
import { useId, useState } from "react";

type ExpandableTextProps = {
  /** The text to show. */
  text: string;
  /** Character count above which the text starts clamped. */
  collapseAfter?: number;
  /** Extra classes for the text block (colour, size). */
  className?: string;
};

/**
 * Render free text with line breaks kept and a Read more toggle when long.
 *
 * @param props - The text, the collapse threshold, and optional classes.
 */
export function ExpandableText({
  text,
  collapseAfter = 280,
  className = "",
}: ExpandableTextProps) {
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  const isLong = text.length > collapseAfter;
  const clamped = isLong && !expanded;

  return (
    <div className="min-w-0">
      <p
        className={[
          "whitespace-pre-wrap break-words",
          clamped ? "line-clamp-4" : "",
          className,
        ].join(" ")}
        id={bodyId}
      >
        {text}
      </p>
      {isLong ? (
        <button
          aria-controls={bodyId}
          aria-expanded={expanded}
          className="mt-1 min-h-11 text-sm font-semibold text-accent outline-none underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => setExpanded((open) => !open)}
          type="button"
        >
          {expanded ? "Show less" : "Read more"}
        </button>
      ) : null}
    </div>
  );
}
