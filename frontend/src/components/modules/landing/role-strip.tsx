import Link from "next/link";

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

type RolePanelProps = {
  eyebrow?: string;
  title: string;
  body: string;
  cta: { href: string; label: string };
  reverse?: boolean;
  visual?: { title: string; lines: string[] };
};


function VisualPlaceholder() {
  return (
    <div className="flex min-h-[260px] w-full items-center justify-center rounded-card border border-border-default bg-surface-2 md:min-h-[320px]">
      <svg
        className="h-12 w-12 text-foreground-subtle/50"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375 0 11-.75 0 .375 0 01.75 0z"
        />
      </svg>
    </div>
  );
}

function RolePanel({ body, cta, eyebrow, reverse, title, visual }: RolePanelProps) {
  return (
    <article
      className={`grid gap-6 rounded-hero border border-border-default bg-surface-1 p-5 md:grid-cols-2 md:gap-10 md:p-8 items-center ${
        reverse ? "md:[&>*:first-child]:order-2" : ""
      }`}
    >
      {isWaitlistMode || !visual ? (
        <VisualPlaceholder />
      ) : (
        <div className="brand-gradient-soft flex min-h-[260px] flex-col justify-between rounded-card p-6 md:min-h-[320px]">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-foreground/80">
            {visual.title}
          </p>
          <ul className="space-y-2 text-sm font-medium text-foreground">
            {visual.lines.map((line) => (
              <li
                className="flex items-center gap-2 rounded-control bg-surface-1/85 px-3 py-2 backdrop-blur"
                key={line}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col justify-center">
        {eyebrow && (
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-foreground-subtle">
            {eyebrow}
          </p>
        )}
        <h3 className="mt-3 font-heading text-2xl font-semibold leading-tight tracking-tight text-foreground md:text-4xl">
          {title}
        </h3>
        <p className="mt-4 text-sm leading-7 text-foreground-muted md:text-base">
          {body}
        </p>
        {isWaitlistMode ? (
          <Link
            className="mt-6 inline-flex min-h-11 w-fit items-center justify-center rounded-control border border-accent/40 bg-surface-1 px-5 text-sm font-medium text-accent transition hover:bg-surface-2 hover:border-accent/60"
            href={cta.href}
          >
            {cta.label}
          </Link>
        ) : (
          <Link
            className="mt-6 inline-flex min-h-12 w-fit items-center rounded-control bg-foreground px-5 text-sm font-medium text-background transition hover:opacity-90"
            href={cta.href}
          >
            {cta.label}
          </Link>
        )}
      </div>
    </article>
  );
}

const panels = [
  {
    title: "Be known for what you've built",
    body: "Build a portfolio of proven frameworks and methodologies that showcase your expertise.",
    cta: isWaitlistMode
      ? { href: "#waitlist-form", label: "Join the Waitlist" }
      : { href: "/register?role=contributor", label: "Start publishing" },
  },
  {
    title: "Create recurring value from existing work",
    body: "Package, license, and maintain the processes and playbooks you've already developed.",
    cta: isWaitlistMode
      ? { href: "#waitlist-form", label: "See Contributor Benefits" }
      : { href: "/explore", label: "Explore the catalog" },
  },
  {
    title: "Build a professional legacy",
    body: "Publish knowledge that continues creating value long after the project ends.",
    cta: isWaitlistMode
      ? { href: "#waitlist-form", label: "Learn More" }
      : { href: "/register", label: "Become a Contributor" },
  },
];

/**
 * Render the three role panels stacked.
 */
export function RoleStrip() {
  return (
    <section className="px-5 pb-16 md:px-10 md:pb-24" id="roles">
      <div className="mx-auto grid w-full max-w-[1280px] gap-4 md:gap-6">
        {panels.map((panel, index) => (
          <RolePanel {...panel} key={panel.title} reverse={index % 2 === 1} />
        ))}
      </div>
    </section>
  );
}


