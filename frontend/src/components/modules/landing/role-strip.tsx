/**
 * Alternating role panels — one per platform role.
 *
 * Each panel pairs a soft gradient pane with explanatory copy and a CTA.
 * Layout flips at `md` so the gradient lives left for odd rows and right for
 * even rows.
 */
import Link from "next/link";

type RolePanelProps = {
  eyebrow: string;
  title: string;
  body: string;
  cta: { href: string; label: string };
  reverse?: boolean;
  visual: { title: string; lines: string[] };
};

function RolePanel({ body, cta, eyebrow, reverse, title, visual }: RolePanelProps) {
  return (
    <article
      className={`grid gap-6 rounded-hero border border-border-default bg-surface-1 p-5 md:grid-cols-2 md:gap-10 md:p-8 ${
        reverse ? "md:[&>*:first-child]:order-2" : ""
      }`}
    >
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

      <div className="flex flex-col justify-center">
        <p className="text-xs font-medium uppercase tracking-[0.08em] text-foreground-subtle">
          {eyebrow}
        </p>
        <h3 className="mt-3 font-heading text-2xl font-semibold leading-tight tracking-tight text-foreground md:text-4xl">
          {title}
        </h3>
        <p className="mt-4 text-sm leading-7 text-foreground-muted md:text-base">
          {body}
        </p>
        <Link
          className="mt-6 inline-flex min-h-12 w-fit items-center rounded-control bg-foreground px-5 text-sm font-medium text-background transition hover:opacity-90"
          href={cta.href}
        >
          {cta.label}
        </Link>
      </div>
    </article>
  );
}

const panels: Omit<RolePanelProps, "reverse">[] = [
  {
    eyebrow: "For Contributors",
    title: "Earn from the playbooks you already run.",
    body: "Publish once. Version forever. Versioning is opinionated — pick a change type and Auracles handles the semver. Versioning notifications, payout splits, and KYC live in one place.",
    cta: { href: "/register?role=contributor", label: "Start publishing" },
    visual: {
      title: "Publish pipeline",
      lines: [
        "Virus scan clean",
        "PII redacted",
        "Originality 0.94",
        "Publish enabled",
      ],
    },
  },
  {
    eyebrow: "For Operators",
    title: "Skip the trial. Run battle-tested playbooks.",
    body: "Filter by sector, function, jurisdiction, and complexity. Buy with single, team, or enterprise license. Download is gated by KYC so the trust floor holds across both sides.",
    cta: { href: "/explore", label: "Explore the catalog" },
    visual: {
      title: "Operator library",
      lines: [
        "Series B Hiring Plan • v1.3",
        "Compliance OS • v2.0",
        "GTM Pricing Playbook • v1.0",
        "Sales Comp Model • v1.1",
      ],
    },
  },
  {
    eyebrow: "For Attestors",
    title: "Lend your reputation. Verify the source.",
    body: "Domain experts review Frameworks against a published rubric. Every attestation is signed, stored, and surfaced on the Framework card — provenance you can audit.",
    cta: { href: "/register?role=attestor", label: "Apply to attest" },
    visual: {
      title: "Attestation queue",
      lines: [
        "GTM Pricing Playbook — assigned",
        "Compliance OS — report drafted",
        "Sales Comp Model — published",
      ],
    },
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
          <RolePanel {...panel} key={panel.eyebrow} reverse={index % 2 === 1} />
        ))}
      </div>
    </section>
  );
}
