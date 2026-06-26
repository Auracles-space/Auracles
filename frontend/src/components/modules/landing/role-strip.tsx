import Link from "next/link";
import {
  CheckCircledIcon,
  DotFilledIcon,
  ArrowDownIcon,
} from "@radix-ui/react-icons";

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

type RolePanelProps = {
  eyebrow?: string;
  title: string;
  body: string;
  cta: { href: string; label: string };
  reverse?: boolean;
  visual?: React.ReactNode;
};

/**
 * Visual mockup representing the framework publishing workspace.
 * Recreates the form layout from the user's sample screenshot.
 */
function ContributorProfileVisual() {
  const Dot = () => (
    <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5 shrink-0" />
  );
  const ChevronDown = () => (
    <svg className="h-3 w-3 text-foreground-subtle shrink-0" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
    </svg>
  );

  return (
    <div className="relative overflow-hidden rounded-2xl border border-border-default bg-surface-2 p-5 md:min-h-[340px] shadow-[0_0_25px_rgba(199,70,52,0.02)] transition duration-300 group-hover:shadow-[0_0_35px_rgba(199,70,52,0.06)] flex flex-col justify-between text-xs select-none">
      {/* Header/Workspace indicator */}
      <div className="flex items-center justify-between border-b border-border-default pb-3 mb-3">
        <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle font-mono">
          Workspace / New Framework
        </span>
        <span className="rounded-badge bg-accent/10 border border-accent/25 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.05em] text-accent">
          Drafting Mode
        </span>
      </div>

      <div className="space-y-3.5">
        {/* Framework Title */}
        <div>
          <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
            <Dot /> Framework Title
          </label>
          <div className="w-full bg-surface-3 border border-border-strong rounded-lg px-3 py-2 text-[11px] text-foreground-muted font-medium font-sans">
            E.g. Enterprise React Architecture Template
          </div>
        </div>

        {/* Description */}
        <div>
          <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
            <Dot /> Description
          </label>
          <div className="w-full bg-surface-3 border border-border-strong rounded-lg px-3 py-2 text-[11px] text-foreground-subtle font-sans min-h-[52px]">
            Describe your framework, methodology, or operational template...
          </div>
        </div>

        {/* Sector */}
        <div>
          <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
            <Dot /> Sector
          </label>
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-muted font-sans">
              <span>Private Equity</span>
              <ChevronDown />
            </div>
            <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-subtle font-sans">
              <span>Industry</span>
              <ChevronDown />
            </div>
            <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-muted font-sans">
              <span>Fund Management</span>
              <ChevronDown />
            </div>
            <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-subtle font-sans">
              <span>Governance</span>
              <ChevronDown />
            </div>
          </div>
        </div>

        {/* Bottom Row - Category & Org Size */}
        <div className="grid grid-cols-2 gap-3.5">
          {/* Category */}
          <div>
            <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
              <Dot /> Category
            </label>
            <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-muted font-sans">
              <span>Framework</span>
              <ChevronDown />
            </div>
          </div>

          {/* Org Size */}
          <div>
            <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
              <Dot /> Organization Size
            </label>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-surface-3 border border-border-strong rounded-lg px-2.5 py-2 flex items-center justify-between text-[11px] text-foreground-muted font-sans">
                <span>(Startup)</span>
                <ChevronDown />
              </div>
              <div className="bg-surface-3 border border-border-strong rounded-lg px-2.5 py-2 flex items-center justify-between text-[11px] text-foreground-muted font-sans">
                <span>$250</span>
                <ChevronDown />
              </div>
            </div>
          </div>
        </div>

        {/* License Types */}
        <div>
          <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-1.5">
            <Dot /> License types
          </label>
          <div className="bg-surface-3 border border-border-strong rounded-lg px-3 py-2 flex items-center justify-between text-[11px] text-foreground-subtle font-sans">
            <span>License Price</span>
            <ChevronDown />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Visual mockup representing active licensing MRR as a Minted Ticket with trend details.
 */
function LicensingRecurringRevenueVisual() {
  const Dot = () => (
    <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5 shrink-0" />
  );

  return (
    <div className="relative overflow-hidden rounded-2xl border border-border-default bg-surface-2 p-5 md:min-h-[340px] shadow-[0_0_25px_rgba(0,0,0,0.01)] flex flex-col justify-between text-xs select-none">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-dashed border-border-default pb-3 mb-3">
        <span className="font-mono text-[9px] tracking-widest text-foreground-subtle uppercase">
          MINTED ASSET REGISTRY
        </span>
        <span className="font-mono text-[9px] text-accent font-bold">
          #AR-4820-OS
        </span>
      </div>

      {/* Barcode Mockup */}
      <div className="flex justify-center items-center gap-[3px] h-6 opacity-35 my-2">
        {[2, 4, 1, 3, 2, 1, 4, 2, 1, 3, 1, 4, 2, 3, 1, 2, 3, 1, 4, 2].map((width, idx) => (
          <div
            key={idx}
            className="h-full bg-foreground"
            style={{ width: `${width}px` }}
          />
        ))}
      </div>

      <div className="space-y-4">
        {/* Chart Label */}
        <div>
          <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-2">
            <Dot /> Recurring Revenue Trend
          </label>
          {/* Mini Bar Chart */}
          <div className="h-20 w-full bg-surface-3 border border-border-strong rounded-xl p-3 flex items-end justify-between gap-2">
            {[
              { label: "JAN", val: "35%", active: false },
              { label: "FEB", val: "45%", active: false },
              { label: "MAR", val: "50%", active: false },
              { label: "APR", val: "68%", active: false },
              { label: "MAY", val: "78%", active: false },
              { label: "JUN", val: "94%", active: true },
            ].map((item, idx) => (
              <div key={idx} className="flex-1 flex flex-col items-center gap-1.5 h-full justify-end">
                <div 
                  className={`w-full rounded-t-sm transition-all duration-500 ${
                    item.active 
                      ? "bg-accent shadow-[0_0_10px_rgba(199,70,52,0.3)]" 
                      : "bg-accent/40 group-hover:bg-accent/60"
                  }`} 
                  style={{ height: item.val }} 
                />
                <span className="text-[7px] font-mono font-bold text-foreground-subtle">{item.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Deployments & Yield Info Row */}
        <div className="grid grid-cols-2 gap-3">
          {/* Active Deployments */}
          <div className="rounded-xl border border-border-strong bg-surface-1 p-3 flex flex-col justify-between min-h-[64px]">
            <span className="text-[8px] font-bold uppercase tracking-[0.05em] text-foreground-subtle">
              OPERATORS
            </span>
            <span className="font-heading text-lg font-bold text-foreground mt-1">
              128 Active
            </span>
          </div>

          {/* Revenue yield */}
          <div className="rounded-xl border border-border-strong bg-surface-1 p-3 flex flex-col justify-between min-h-[64px]">
            <span className="text-[8px] font-bold uppercase tracking-[0.05em] text-foreground-subtle">
              MONTHLY YIELD
            </span>
            <span className="font-heading text-lg font-bold text-foreground mt-1">
              $4,820.00
            </span>
          </div>
        </div>

        {/* Growth badge */}
        <div className="rounded-xl border border-border-strong bg-surface-1 p-3 flex items-center justify-between">
          <span className="text-[9px] font-bold uppercase tracking-[0.05em] text-foreground-muted">
            Performance Index
          </span>
          <span className="rounded-badge bg-[#16A34A]/10 border border-[#16A34A]/30 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.05em] text-[#16A34A] flex items-center gap-1">
            <CheckCircledIcon className="h-3 w-3" />
            +18.4% MRR
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Visual mockup showing the playbook workflow verification pipeline.
 */
function ProfessionalLegacyVisual() {
  const Dot = () => (
    <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5 shrink-0" />
  );

  return (
    <div className="relative overflow-hidden rounded-2xl border border-border-default bg-surface-2 p-5 md:min-h-[340px] shadow-[0_0_25px_rgba(0,0,0,0.01)] flex flex-col justify-between text-xs select-none">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-default pb-3 mb-3">
        <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-foreground-subtle font-mono">
          OPERATIONAL LIFECYCLE
        </span>
        <span className="rounded-badge bg-foreground-subtle/10 border border-foreground-subtle/25 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.05em] text-foreground-subtle font-mono">
          v1.4.0
        </span>
      </div>

      <label className="flex items-center text-[10px] font-bold uppercase tracking-[0.05em] text-foreground mb-3">
        <Dot /> Verification Pipeline
      </label>

      {/* Vertical Steps Stacks */}
      <div className="space-y-3 relative pl-3.5 before:absolute before:left-1 before:top-2 before:bottom-2 before:w-[1px] before:bg-border-strong">
        
        {/* Step 1: Draft Published */}
        <div className="relative rounded-xl border border-border-strong bg-surface-1 p-3 flex items-center justify-between">
          <div className="absolute -left-[18px] top-4.5 h-2 w-2 rounded-full bg-[#16A34A] ring-4 ring-surface-2" />
          <div>
            <h5 className="text-[11px] font-bold text-foreground">1. Refine Raw Expertise</h5>
            <p className="text-[9px] text-foreground-muted mt-0.5">Package methodologies into SOP playbooks</p>
          </div>
          <span className="rounded-badge bg-[#16A34A]/10 border border-[#16A34A]/30 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.05em] text-[#16A34A]">
            Published
          </span>
        </div>

        {/* Step 2: Attestation Verified */}
        <div className="relative rounded-xl border border-border-strong bg-surface-1 p-3 flex items-center justify-between">
          <div className="absolute -left-[18px] top-4.5 h-2 w-2 rounded-full bg-[#F59E0B] ring-4 ring-surface-2" />
          <div>
            <h5 className="text-[11px] font-bold text-foreground">2. Peer Attestation</h5>
            <p className="text-[9px] text-foreground-muted mt-0.5">Attestors verify compliance & quality</p>
          </div>
          <span className="rounded-badge bg-[#F59E0B]/10 border border-[#F59E0B]/30 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.05em] text-[#F59E0B]">
            In Review
          </span>
        </div>

        {/* Step 3: Global Deployment */}
        <div className="relative rounded-xl border border-border-strong bg-surface-1 p-3 flex items-center justify-between opacity-60">
          <div className="absolute -left-[18px] top-4.5 h-2 w-2 rounded-full bg-foreground-subtle ring-4 ring-surface-2" />
          <div>
            <h5 className="text-[11px] font-bold text-foreground">3. Global Implementation</h5>
            <p className="text-[9px] text-foreground-muted mt-0.5">Operators license & launch workspace</p>
          </div>
          <span className="rounded-badge bg-foreground-subtle/10 border border-foreground-subtle/30 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.05em] text-foreground-subtle">
            Escrow
          </span>
        </div>

      </div>
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
      <div className="w-full">
        {visual}
      </div>

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
    visual: <ContributorProfileVisual />,
  },
  {
    title: "Create recurring value from existing work",
    body: "Package, license, and maintain the processes and playbooks you've already developed.",
    cta: isWaitlistMode
      ? { href: "#waitlist-form", label: "See Contributor Benefits" }
      : { href: "/explore", label: "Explore the catalog" },
    visual: <LicensingRecurringRevenueVisual />,
  },
  {
    title: "Build a professional legacy",
    body: "Publish knowledge that continues creating value long after the project ends.",
    cta: isWaitlistMode
      ? { href: "#waitlist-form", label: "Learn More" }
      : { href: "/register", label: "Become a Contributor" },
    visual: <ProfessionalLegacyVisual />,
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
