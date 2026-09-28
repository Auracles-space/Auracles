/**
 * Live demand teaser for the contributor section of the landing page.
 *
 * Names what people are searching for and not finding, in their own words.
 * Concrete current demand is what persuades someone to contribute; a link
 * labelled "market demand" is not.
 *
 * Silent whenever there is nothing real to say — an empty box here reads as a
 * broken section, and "nobody wants anything" is the opposite of the message.
 */
import { ArrowRightIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import type { DemandTerm } from "@/lib/generated/types.gen";

type DemandTeaserProps = {
  /** Top demand terms, or null when the demand API was unavailable. */
  terms: DemandTerm[] | null;
};

/** How many terms read as evidence without becoming a list. */
const TEASER_TERMS = 3;

/**
 * Render the live demand teaser, or nothing at all.
 *
 * @param terms - Top demand terms, or null when unavailable.
 */
export function DemandTeaser({ terms }: DemandTeaserProps) {
  if (terms === null || terms.length === 0) {
    return null;
  }

  const shown = terms.slice(0, TEASER_TERMS);

  return (
    <div className="mt-8 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Asked for right now
      </p>
      <p className="mt-3 text-base leading-7 text-foreground">
        People are searching for{" "}
        {shown.map((row, index) => (
          <span key={row.term}>
            <span className="font-semibold">{row.term}</span>
            {index < shown.length - 2 ? ", " : null}
            {index === shown.length - 2 ? " and " : null}
          </span>
        ))}{" "}
        — and finding nothing.
      </p>
      <Link
        className="mt-4 inline-flex min-h-12 items-center gap-1.5 text-sm font-semibold text-accent transition-colors hover:text-accent/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        href="/demand"
      >
        See what the market is asking for
        <ArrowRightIcon aria-hidden="true" className="h-4 w-4" />
      </Link>
    </div>
  );
}
