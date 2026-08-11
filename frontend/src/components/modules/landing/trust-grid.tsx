/**
 * "Become an Auracle" — the four-step contributor entry ladder.
 *
 * Rendered as a connected sequence rather than a card grid: the order is the
 * information here, and it keeps this section visually distinct from the
 * `HowItWorks` bento and the `RoleStrip` panels, which sit either side of it.
 */
import {
  UploadIcon,
  BadgeIcon,
  MagnifyingGlassIcon,
  BarChartIcon,
} from "@radix-ui/react-icons";

const entrySteps = [
  {
    label: "Publish your Framework",
    body: "Upload the playbooks, templates, and operating systems you've developed through real-world experience.",
    icon: UploadIcon,
  },
  {
    label: "Build credibility",
    body: "Auracles verifies contributors and reviews submissions before publication.",
    icon: BadgeIcon,
  },
  {
    label: "Get discovered",
    body: "Organizations browse the marketplace to find trusted Frameworks for specific challenges.",
    icon: MagnifyingGlassIcon,
  },
  {
    label: "Earn and grow",
    body: "Generate licensing revenue, build reputation, and expand your professional portfolio.",
    icon: BarChartIcon,
  },
];

/**
 * Render the contributor entry ladder.
 */
export function TrustGrid() {
  return (
    <section className="bg-surface-2 px-5 py-16 md:px-10 md:py-24" id="become">
      {/* The intro sticks alongside the steps at `lg`, so a wide viewport is
          filled by the section rather than leaving half of it empty. */}
      <div className="mx-auto grid w-full max-w-[1280px] gap-12 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:gap-20">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <h2 className="font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            How to become an Auracle
          </h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-foreground-muted">
            Four steps from professional knowledge to a trusted, reusable, and
            licensable asset.
          </p>
        </div>

        <ol className="lg:pt-2">
          {entrySteps.map((step, index) => {
            const Icon = step.icon;
            const isLast = index === entrySteps.length - 1;

            return (
              <li className="relative flex gap-5 md:gap-8" key={step.label}>
                {/* Numeral rail — the connecting hairline stops at the last step. */}
                <div className="flex shrink-0 flex-col items-center">
                  <span className="flex h-11 w-11 items-center justify-center rounded-full border border-border-strong bg-surface-1 font-heading text-base font-bold text-accent">
                    {index + 1}
                  </span>
                  {!isLast && (
                    <span
                      aria-hidden="true"
                      className="w-px flex-1 bg-border-strong"
                    />
                  )}
                </div>

                <div className={isLast ? "pb-0 pt-1.5" : "pb-10 pt-1.5 md:pb-14"}>
                  <h3 className="flex flex-wrap items-center gap-x-3 gap-y-1 font-heading text-xl font-semibold text-foreground md:text-2xl">
                    <Icon aria-hidden="true" className="h-5 w-5 shrink-0 text-accent" />
                    {step.label}
                  </h3>
                  <p className="mt-2 max-w-xl text-sm leading-7 text-foreground-muted md:text-base">
                    {step.body}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
