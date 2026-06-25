import {
  UploadIcon,
  BadgeIcon,
  MagnifyingGlassIcon,
  BarChartIcon,
} from "@radix-ui/react-icons";

const waitlistPillars = [
  {
    label: "Publish your Framework",
    body: "Upload the playbooks, templates, and operating systems you've developed through real-world experience.",
    icon: <UploadIcon className="h-6 w-6 text-accent" />,
  },
  {
    label: "Build credibility",
    body: "Auracles verifies contributors and reviews submissions before publication.",
    icon: <BadgeIcon className="h-6 w-6 text-accent" />,
  },
  {
    label: "Get discovered",
    body: "Organizations browse the marketplace to find trusted Frameworks for specific challenges.",
    icon: <MagnifyingGlassIcon className="h-6 w-6 text-accent" />,
  },
  {
    label: "Earn and grow",
    body: "Generate licensing revenue, build reputation, and expand your professional portfolio.",
    icon: <BarChartIcon className="h-6 w-6 text-accent" />,
  },
];


/**
 * Render the trust pillars grid.
 */
export function TrustGrid() {
  return (
    <section className="bg-surface-2 px-5 py-16 md:px-10 md:py-24" id="trust">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="flex flex-col items-start justify-between gap-8 md:flex-row md:items-end mb-12">
          <div className="max-w-2xl">
            <h2 className="font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
              How To Become An Auracle
            </h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-foreground-muted">
              From publishing your expertise to building reputation and earning from it, Auracles helps turn professional knowledge into trusted, reusable assets
            </p>
          </div>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {waitlistPillars.map((pillar) => (
            <article
              className="group relative overflow-hidden rounded-[32px] border border-border-default bg-surface-1 p-8 shadow-bento transition hover:-translate-y-1 hover:shadow-hero"
              key={pillar.label}
            >
              <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-peach/5 blur-2xl transition duration-500 group-hover:bg-brand-peach/10" />
              <div className="relative z-10">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2">
                  {pillar.icon}
                </div>
                <h3 className="mt-6 font-heading text-xl font-semibold text-foreground md:text-2xl">
                  {pillar.label}
                </h3>
                <p className="mt-3 text-sm leading-7 text-foreground-muted">
                  {pillar.body}
                </p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}


