/**
 * Shared shell for auth workflow pages.
 *
 * Keeps the Slice 10 auth pages visually consistent with the Brand Book:
 * mobile-first, border-based separation, warm light surfaces, and no nested
 * cards. The shell contains no API behavior.
 */
import type { ReactNode } from "react";

type AuthPageShellProps = {
  children: ReactNode;
  eyebrow: string;
  title: string;
  summary: string;
};

/**
 * Render an auth page with a contextual side panel and a single form surface.
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
    <main className="min-h-screen bg-background px-5 py-10 text-foreground md:px-10 md:py-16 lg:py-20">
      <section className="mx-auto grid w-full max-w-[1280px] gap-6 md:grid-cols-[minmax(0,0.82fr)_minmax(420px,0.68fr)] md:items-start">
        <aside className="border-b border-border-strong pb-6 md:border-b-0 md:border-r md:pb-0 md:pr-8">
          <div className="font-heading text-xl font-semibold">Auracles</div>
          <p className="mt-10 text-xs font-medium uppercase tracking-[0.05em] text-foreground-subtle">
            {eyebrow}
          </p>
          <h1 className="mt-3 max-w-2xl font-heading text-3xl font-semibold text-foreground md:text-5xl">
            {title}
          </h1>
          <p className="mt-5 max-w-xl text-sm leading-7 text-foreground-muted md:text-base">
            {summary}
          </p>
        </aside>

        <div className="rounded-card border border-border-strong bg-surface-2 p-5 md:p-6">
          {children}
        </div>
      </section>
    </main>
  );
}
