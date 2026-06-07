/**
 * Landing hero — signature gradient blob behind centered headline + CTAs.
 *
 * Mobile-first: stacks vertically with the gradient block scaled down. Above
 * `md` the gradient panel grows and a preview product card overlays it.
 */
import Link from "next/link";

const trustedBy = [
  "McKinsey alumni",
  "Stripe ops",
  "Y Combinator partners",
  "Bain associates",
];

/**
 * Render the Auracles marketing hero.
 */
export function LandingHero() {
  return (
    <section className="relative overflow-hidden px-5 pb-16 pt-12 md:px-10 md:pt-20 lg:pt-24">
      <div className="mx-auto w-full max-w-[1280px]">


        <h1 className="mx-auto mt-6 max-w-3xl text-balance text-center font-heading text-4xl font-semibold leading-[1.05] tracking-tight text-foreground md:text-6xl lg:text-7xl">
          License professional knowledge that{" "}
          <span className="brand-text-gradient">actually works.</span>
        </h1>

        <p className="mx-auto mt-5 max-w-xl text-balance text-center text-base leading-7 text-foreground-muted md:text-lg">
          Buy, run, and verify expert Frameworks built by operators who have
          shipped them. Skip the trial and error.
        </p>

        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control bg-accent px-6 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
            href="/explore"
          >
            Browse Frameworks
          </Link>
          <Link
            className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control border border-border-strong bg-surface-1 px-6 text-sm font-medium text-foreground transition hover:bg-surface-2"
            href="/register"
          >
            Become a Contributor
          </Link>
        </div>

        <p className="mt-10 text-center text-xs font-medium uppercase tracking-[0.08em] text-foreground-subtle">
          Trusted by operators from
        </p>
        <ul className="mx-auto mt-3 flex max-w-3xl flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-foreground-muted">
          {trustedBy.map((name) => (
            <li className="font-medium" key={name}>
              {name}
            </li>
          ))}
        </ul>

        <div className="relative mx-auto mt-16 max-w-5xl md:mt-24">
          <div className="absolute inset-0 -z-10 mx-auto max-w-4xl opacity-80 blur-3xl brand-gradient" />
          <div className="rounded-hero border border-border-default bg-surface-1/60 p-2 shadow-hero backdrop-blur-md">
            <div className="rounded-[28px] border border-border-default bg-surface-1 p-4 shadow-bento md:p-6">
              {/* Browser Chrome */}
              <div className="flex items-center justify-between border-b border-border-default pb-4">
                <div className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-[#FF5F56]" />
                  <span className="h-3 w-3 rounded-full bg-[#FFBD2E]" />
                  <span className="h-3 w-3 rounded-full bg-[#27C93F]" />
                </div>
                <div className="flex h-8 w-64 items-center justify-center rounded-badge bg-surface-2 px-3 text-[11px] font-medium text-foreground-muted">
                  <svg
                    className="mr-2 h-3 w-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4"
                    />
                  </svg>
                  auracles.space / explore
                </div>
                <span className="h-3 w-3 rounded-full bg-transparent" />
              </div>

              {/* Dashboard Mockup */}
              <div className="mt-4 flex flex-col gap-4 md:flex-row">
                <div className="hidden w-48 flex-col gap-2 rounded-xl bg-surface-2 p-3 md:flex">
                  <div className="h-8 w-full rounded bg-surface-3" />
                  <div className="h-8 w-full rounded bg-surface-3" />
                  <div className="h-8 w-3/4 rounded bg-surface-3" />
                  <div className="mt-8 h-4 w-1/2 rounded bg-border-strong" />
                  <div className="mt-2 h-20 w-full rounded bg-surface-3" />
                </div>
                
                <div className="flex-1 space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-heading text-lg font-semibold text-foreground">Overview</h3>
                      <p className="text-sm text-foreground-muted">Performance across frameworks</p>
                    </div>
                    <div className="flex gap-2">
                      <div className="h-8 w-24 rounded bg-surface-2" />
                      <div className="h-8 w-8 rounded bg-accent" />
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-3">
                    {[
                      { label: "Active Licenses", value: "2,405" },
                      { label: "Total Revenue", value: "$48.2k" },
                      { label: "Growth", value: "+12.4%" },
                    ].map((stat) => (
                      <div key={stat.label} className="rounded-xl border border-border-default bg-surface-2 p-4">
                        <p className="text-xs text-foreground-muted">{stat.label}</p>
                        <p className="mt-1 font-heading text-xl font-semibold text-foreground">{stat.value}</p>
                      </div>
                    ))}
                  </div>

                  <div className="h-48 w-full rounded-xl border border-border-default bg-surface-2 p-4">
                    {/* Placeholder for chart */}
                    <div className="flex h-full items-end justify-between gap-2 opacity-50">
                      {[40, 60, 30, 80, 50, 90, 70].map((height, i) => (
                        <div
                          key={i}
                          className="w-full rounded-t-sm bg-accent"
                          style={{ height: `${height}%` }}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
