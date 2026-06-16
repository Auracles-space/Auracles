/**
 * Shared shell for auth workflow pages.
 *
 * Mobile-first: stacks vertically with a compact branded panel above and the
 * form card below. From `md` up, the branded panel sits on the left as a soft
 * gradient pane carrying the page eyebrow + headline + summary.
 *
 * Uses the refreshed Auracles palette: warm cream surfaces, charcoal text,
 * signature peach-to-indigo soft gradient accent.
 */
import type { ReactNode } from "react";
import { BrandLogo } from "@/components/ui/brand-logo";

type AuthPageShellProps = {
  children: ReactNode;
  eyebrow: string;
  title: string;
  summary: string;
};

/**
 * Render an auth page with a soft-gradient context panel and a single form card.
 *
 * @param props - Page copy and child form content.
 */
export function AuthPageShell({
  children,
  eyebrow,
  summary,
  title,
}: AuthPageShellProps) {
  return (
    <main className="flex min-h-screen flex-col justify-center bg-background px-5 py-8 text-foreground md:px-10 md:py-14">
      {/* Mobile-only brand logo above the card */}
      <div className="mx-auto mb-6 flex w-full max-w-[1180px] justify-start md:hidden">
        <BrandLogo className="h-8 w-32" />
      </div>

      <section className="mx-auto grid w-full max-w-[1180px] gap-4 md:grid-cols-[minmax(0,1fr)_minmax(380px,0.85fr)] md:items-stretch md:gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(420px,0.85fr)] lg:gap-8">
        {/* Desktop-only branded sidebar panel */}
        <aside className="brand-gradient-soft relative hidden flex-col justify-between overflow-hidden rounded-hero border border-border-default p-6 lg:p-8 xl:p-10 md:flex">
          <div className="flex items-center gap-2">
            <BrandLogo className="h-8 w-32" />
          </div>

          <div className="mt-10 lg:mt-16 xl:mt-20">
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-accent">
              {eyebrow}
            </p>
            <h1 className="mt-3 max-w-md font-heading text-3xl lg:text-4xl xl:text-5xl font-bold leading-tight tracking-tight text-foreground">
              {title}
            </h1>
            <p className="mt-4 max-w-md text-sm lg:text-base leading-relaxed text-foreground-muted">
              {summary}
            </p>
          </div>

          <div className="mt-8 lg:mt-10">
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-accent">
              Trust by design
            </p>
            <ul className="mt-4 space-y-3 text-sm font-medium text-foreground">
              <li className="flex items-center gap-3">
                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white shadow-sm">
                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                Pipeline checks before publish
              </li>
              <li className="flex items-center gap-3">
                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white shadow-sm">
                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                KYC on both sides
              </li>
              <li className="flex items-center gap-3">
                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white shadow-sm">
                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                Audit log from day one
              </li>
            </ul>
          </div>
        </aside>

        <div className="rounded-[32px] border border-border-default bg-surface-1 p-5 shadow-bento md:p-8 lg:p-10">
          {children}
        </div>
      </section>
    </main>
  );
}
