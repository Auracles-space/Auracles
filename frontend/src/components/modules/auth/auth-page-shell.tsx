/**
 * Shared shell for auth workflow pages.
 *
 * Mobile-first: places page context before the form so recovery and onboarding
 * tasks start with clear intent. From `lg` up, the context panel and form card
 * sit side-by-side in the Auracles bento surface system.
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
 * Render an auth page with a context panel and a single task card.
 *
 * @param props - Page copy and child form content.
 */
export function AuthPageShell({
  children,
  eyebrow,
  summary,
  title,
}: AuthPageShellProps) {
  const trustItems = [
    "Session state is verified before workspace access.",
    "Sensitive account changes use email and 2FA checks.",
    "Marketplace actions are audit logged.",
  ];

  return (
    <main className="flex min-h-screen items-center bg-background px-5 py-6 text-foreground md:px-10 md:py-10">
      <section className="mx-auto grid w-full max-w-[1180px] gap-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(380px,0.8fr)] lg:items-stretch lg:gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.78fr)]">
        <aside
          aria-label={`${eyebrow} context`}
          className="flex flex-col justify-between rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8 lg:p-10"
        >
          <div>
            <BrandLogo className="h-8 w-32" />

            <h1 className="mt-8 max-w-xl text-balance font-heading text-3xl font-bold leading-tight tracking-tight text-foreground md:text-4xl xl:text-5xl">
              {title}
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-7 text-foreground-muted md:text-base">
              {summary}
            </p>
          </div>

          <div className="mt-8 border-t border-border-default pt-5 md:mt-10 md:pt-6">
            <p className="font-heading text-sm font-semibold text-foreground">
              Trust controls stay visible.
            </p>
            <ul className="mt-4 grid gap-3 text-sm font-medium leading-6 text-foreground-muted sm:grid-cols-3 lg:grid-cols-1">
              {trustItems.map((item) => (
                <li className="flex gap-3 rounded-xl bg-surface-2 p-3" key={item}>
                  <span
                    aria-hidden="true"
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-lg bg-accent text-white"
                  >
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <div className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8 lg:p-10">
          {children}
        </div>
      </section>
    </main>
  );
}
