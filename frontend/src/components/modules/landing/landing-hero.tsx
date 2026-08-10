/**
 * Landing hero — signature gradient blob behind centered headline + CTAs.
 *
 * Mobile-first: stacks vertically with the gradient block scaled down. Above
 * `md` the gradient panel grows and a preview product card overlays it.
 */
import Link from "next/link";

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

const targetAudiences = [
  "Professionals",
  "Operators",
  "Investors",
  "Consultants",
  "Domain experts",
];

/**
 * Render the Auracles marketing hero.
 */
export function LandingHero() {
  return (
    <section className="relative overflow-hidden px-5 pb-16 pt-12 md:px-10 md:pt-20 lg:pt-24">
      <div className="mx-auto w-full max-w-[1280px]">

        <h1 className="mx-auto mt-6 max-w-3xl text-balance text-center font-heading text-4xl font-semibold leading-tight tracking-tight text-foreground md:text-6xl lg:text-7xl">
          Marketplace for operational frameworks
        </h1>

        <p className="mx-auto mt-5 max-w-2xl text-balance text-center text-base leading-7 text-foreground-muted md:text-lg">
          Get all the tools and support needed to launch your operations in any industry
        </p>

        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          {isWaitlistMode ? (
            <>
              <Link
                className="inline-flex h-12 min-w-[220px] items-center justify-center rounded-control bg-accent px-6 text-sm font-medium text-white shadow-sm transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                href="#waitlist-form"
              >
                Join the Contributor Waitlist
              </Link>
              <Link
                className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control border border-border-strong bg-surface-1 px-6 text-sm font-medium text-foreground transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                href="#how-it-works"
              >
                See How It Works
              </Link>
            </>
          ) : (
            <>
              <Link
                className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control bg-accent px-6 text-sm font-medium text-white shadow-sm transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                href="/explore"
              >
                Browse the catalog
              </Link>
              <Link
                className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control border border-border-strong bg-surface-1 px-6 text-sm font-medium text-foreground transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                href="/register"
              >
                Become a Contributor
              </Link>
            </>
          )}
        </div>

        <p className="mt-10 text-center text-xs font-semibold uppercase tracking-[0.08em] text-foreground-subtle">
          Built for:
        </p>
        <div className="mx-auto mt-3 flex max-w-3xl flex-wrap items-center justify-center gap-x-3 gap-y-1.5 text-sm font-medium text-foreground-muted">
          {targetAudiences.map((audience, idx) => (
            <div key={audience} className="flex items-center gap-3">
              <span>{audience}</span>
              {idx < targetAudiences.length - 1 && (
                <span className="text-foreground-subtle/50" aria-hidden="true">|</span>
              )}
            </div>
          ))}
        </div>



        {/*
          Illustrative product preview. Every figure below is sample data, not a
          platform metric, so the whole block is hidden from assistive tech —
          otherwise a screen reader announces the mock dashboard as real content.
        */}
        <div aria-hidden="true" className="relative mx-auto mt-16 max-w-5xl md:mt-24">
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

              <div className="mt-4 flex flex-col gap-4 md:flex-row">
                {/* Sidebar Navigation */}
                <div className="hidden w-48 flex-col justify-between rounded-xl bg-surface-2 p-3 border border-border-strong md:flex text-xs select-none">
                  <div className="space-y-4">
                    {/* Logo / Brand Indicator */}
                    <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default pb-3">
                      <div className="h-5 w-5 rounded bg-accent flex items-center justify-center text-[10px] font-bold text-white">
                        A
                      </div>
                      <span className="font-heading font-bold text-foreground tracking-tight text-[11px]">
                        Auracles Console
                      </span>
                    </div>

                    {/* Menu Items */}
                    <div className="space-y-1">
                      {[
                        { label: "Explore Market", active: true, icon: (
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                        )},
                        { label: "My Workspace", active: false, icon: (
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
                        )},
                        { label: "Attestations", active: false, icon: (
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
                        )},
                        { label: "Transactions", active: false, icon: (
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                        )},
                        { label: "Settings", active: false, icon: (
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                        )}
                      ].map((item) => (
                        <div
                          key={item.label}
                          className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg font-medium ${
                            item.active
                              ? "bg-accent/10 border border-accent/25 text-accent"
                              : "text-foreground-muted"
                          }`}
                        >
                          {item.icon}
                          <span>{item.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Sidebar User Profile Footer */}
                  <div className="flex items-center gap-2 border-t border-border-default pt-3 mt-8 px-1">
                    <div className="h-7 w-7 rounded-lg bg-accent/10 border border-accent/25 flex items-center justify-center text-accent font-bold text-[10px]">
                      AR
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] font-bold text-foreground truncate">Alex Rivers</p>
                      <p className="text-[10px] text-foreground-subtle truncate">S-Tier Contributor</p>
                    </div>
                  </div>
                </div>
                
                <div className="flex-1 space-y-4">
                  {/* Dashboard Content Header */}
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <h3 className="font-heading text-base font-bold text-foreground">Operator Cockpit</h3>
                      <p className="text-[10px] text-foreground-muted font-medium">Real-time attestation and license tracking</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Time Range Selector */}
                      <div className="h-7 px-2.5 rounded-lg border border-border-strong bg-surface-2 text-[10px] font-bold text-foreground-muted flex items-center gap-1 select-none">
                        <span>Last 30 Days</span>
                        <svg className="h-2.5 w-2.5 opacity-60" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" /></svg>
                      </div>
                      {/* Export Button */}
                      <div className="h-7 px-2.5 rounded-lg border border-border-strong bg-surface-2 text-[10px] font-bold text-foreground-muted flex items-center gap-1 select-none">
                        <svg className="h-2.5 w-2.5 opacity-70" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
                        <span>Export</span>
                      </div>
                    </div>
                  </div>

                  {/* Bento Metrics Cards */}
                  <div className="grid gap-3 sm:grid-cols-3">
                    {[
                      { label: "Active Licenses", value: "2,405", sub: "+8.2% this month", trend: "up" },
                      { label: "Total Revenue (MRR)", value: "$48,210", sub: "+12.4% vs last Q", trend: "up" },
                      { label: "Attested Frameworks", value: "18 Assets", sub: "99.4% Compliance", trend: "neutral" },
                    ].map((stat) => (
                      <div key={stat.label} className="rounded-xl border border-border-strong bg-surface-2 p-3.5 flex flex-col justify-between shadow-sm relative select-none">
                        <div className="flex items-center justify-between">
                          <p className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-subtle flex items-center">
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5 shrink-0" />
                            {stat.label}
                          </p>
                        </div>
                        <div className="mt-2.5 flex items-baseline justify-between">
                          <h4 className="font-heading text-xl font-bold text-foreground tracking-tight">{stat.value}</h4>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
                            stat.trend === "up" 
                              ? "bg-success/10 border-success/25 text-success" 
                              : "bg-foreground-subtle/10 border-foreground-subtle/25 text-foreground-subtle"
                          }`}>
                            {stat.sub}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Revenue Trend Chart */}
                  <div className="rounded-xl border border-border-strong bg-surface-2 p-4 flex flex-col justify-between gap-3 shadow-sm select-none">
                    <div className="flex items-center justify-between border-b border-border-default pb-2">
                      <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground flex items-center">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5" />
                        Monthly Revenue Yield ($)
                      </span>
                      <div className="flex items-center gap-3 text-[10px] font-mono font-bold text-foreground-subtle">
                        <div className="flex items-center gap-1">
                          <span className="h-1.5 w-1.5 rounded-full bg-accent/40" />
                          <span>Estimated</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                          <span>Actual Payouts</span>
                        </div>
                      </div>
                    </div>
                    
                    {/* High-Fidelity Chart Area */}
                    <div className="relative h-32 w-full flex items-end justify-between gap-3 pt-4 px-2">
                      {/* Background Grid Lines */}
                      <div className="absolute inset-0 flex flex-col justify-between pointer-events-none opacity-40 py-2 border-b border-border-default/60">
                        <div className="border-t border-dashed border-border-strong/50 w-full" />
                        <div className="border-t border-dashed border-border-strong/50 w-full" />
                        <div className="border-t border-dashed border-border-strong/50 w-full" />
                      </div>

                      {/* Chart Bars */}
                      {[
                        { month: "JAN", est: "30%", act: "45%" },
                        { month: "FEB", est: "40%", act: "55%" },
                        { month: "MAR", est: "35%", act: "48%" },
                        { month: "APR", est: "60%", act: "75%" },
                        { month: "MAY", est: "55%", act: "72%" },
                        { month: "JUN", est: "75%", act: "90%", active: true },
                      ].map((item, idx) => (
                        <div key={idx} className="flex-1 flex flex-col items-center gap-1.5 h-full justify-end relative z-10">
                          {/* Double bar columns */}
                          <div className="w-full flex items-end justify-center gap-[2px] h-full">
                            <div 
                              className="w-1.5 rounded-t-sm bg-accent/30" 
                              style={{ height: item.est }}
                            />
                            <div 
                              className={`w-2.5 rounded-t-sm transition-all duration-300 ${
                                item.active 
                                  ? "bg-accent shadow-[0_0_12px_rgba(199,70,52,0.35)]" 
                                  : "bg-accent/80"
                              }`} 
                              style={{ height: item.act }}
                            />
                          </div>
                          <span className="text-[9px] font-mono font-bold text-foreground-subtle tracking-wider mt-1">{item.month}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Active Frameworks List */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground flex items-center">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent mr-1.5" />
                        Active Workspace Frameworks
                      </span>
                      <span className="text-[10px] font-mono text-foreground-subtle">
                        2 Workspace Units Active
                      </span>
                    </div>

                    <div className="grid gap-2 sm:grid-cols-2">
                      {[
                        { title: "ISO-27001 Security Audit SOP", cat: "Security", lic: "42 Licenses", yield: "$1,680.00/mo", status: "Published" },
                        { title: "Private Equity Financial Model", cat: "Financials", lic: "28 Licenses", yield: "$2,240.00/mo", status: "In Review" },
                      ].map((fw) => (
                        <div key={fw.title} className="rounded-xl border border-border-strong bg-surface-2 p-3 flex items-center justify-between text-[10px]">
                          <div className="min-w-0 pr-2">
                            <h5 className="font-bold text-foreground truncate">{fw.title}</h5>
                            <div className="flex items-center gap-2 mt-1 text-[10px] text-foreground-subtle font-medium">
                              <span className="bg-surface-3 px-1.5 py-0.5 rounded border border-border-strong">{fw.cat}</span>
                              <span>{fw.lic}</span>
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <p className="font-heading font-bold text-foreground">{fw.yield}</p>
                            <span className={`inline-block mt-1 text-[9px] font-bold uppercase tracking-wider rounded px-1 py-0.25 ${
                              fw.status === "Published" 
                                ? "bg-success/10 text-success border border-success/25" 
                                : "bg-warning/10 text-warning border border-warning/25"
                            }`}>
                              {fw.status}
                            </span>
                          </div>
                        </div>
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
