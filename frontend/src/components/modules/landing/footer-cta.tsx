/**
 * Footer CTA strip + site footer.
 *
 * Bottom gradient panel mirrors the hero blob and closes the page on the
 * marketplace's primary call: register. Below, a slim site footer with
 * legal + contact links.
 */
import Link from "next/link";

const footerGroups = [
  {
    title: "Platform",
    links: [
      { href: "/explore", label: "Explore" },
      { href: "/register?role=contributor", label: "Become a Contributor" },
      { href: "/register?role=attestor", label: "Apply to attest" },
      { href: "/login", label: "Sign in" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "#how-it-works", label: "How it works" },
      { href: "#trust", label: "Trust" },
      { href: "#pricing", label: "License options" },
      { href: "#faq", label: "FAQ" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "mailto:hello@auracles.space", label: "Contact" },
      { href: "/terms", label: "Terms" },
      { href: "/privacy", label: "Privacy" },
      { href: "/security", label: "Security" },
    ],
  },
];

/**
 * Render the closing gradient CTA and the site footer.
 */
export function FooterCta() {
  return (
    <>
      <section className="w-full">
        <div className="brand-gradient flex w-full flex-col items-center px-5 py-24 text-center md:py-32">
          <h2 className="max-w-3xl font-heading text-4xl font-bold leading-tight tracking-tight text-white md:text-5xl lg:text-6xl">
            Stop reinventing what someone already shipped.
          </h2>
          <p className="mt-6 max-w-xl text-base leading-7 text-white/90 md:text-lg">
            License a Framework, run it tomorrow, and verify it landed. Your
            first download is one signup away.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              className="inline-flex h-14 min-w-[200px] items-center justify-center rounded-control bg-foreground px-8 text-base font-bold text-background shadow-lg transition hover:bg-foreground/90"
              href="/register"
            >
              Create an account
            </Link>
            <Link
              className="inline-flex h-14 min-w-[200px] items-center justify-center rounded-control border-2 border-white bg-transparent px-8 text-base font-bold text-white transition hover:bg-white hover:text-foreground"
              href="/explore"
            >
              Browse the catalog
            </Link>
          </div>
        </div>
      </section>

      <footer className="bg-background">
        <div className="mx-auto grid w-full max-w-[1280px] gap-10 px-5 py-16 md:grid-cols-[1.4fr_1fr_1fr_1fr] md:px-10">
          <div>
            <div className="flex items-center gap-2">
              <div className="h-6 w-6 rounded-md bg-accent"></div>
              <div className="font-heading text-xl font-bold text-foreground">
                Auracles
              </div>
            </div>
            <p className="mt-4 max-w-xs text-sm leading-7 text-foreground-muted">
              The marketplace for professional knowledge — licensed, attested,
              and audit-ready.
            </p>
          </div>
          {footerGroups.map((group) => (
            <div key={group.title}>
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-foreground-subtle">
                {group.title}
              </p>
              <ul className="mt-6 space-y-4 text-sm font-medium text-foreground-muted">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      className="transition hover:text-accent"
                      href={link.href}
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="border-t border-border-default">
          <div className="mx-auto flex w-full max-w-[1280px] flex-col justify-between gap-4 px-5 py-8 text-xs font-medium text-foreground-subtle md:flex-row md:px-10">
            <p>© {new Date().getFullYear()} Auracles. All rights reserved.</p>
            <div className="flex gap-6">
              <Link href="#" className="hover:text-foreground">Twitter</Link>
              <Link href="#" className="hover:text-foreground">LinkedIn</Link>
              <Link href="#" className="hover:text-foreground">GitHub</Link>
            </div>
          </div>
        </div>
      </footer>
    </>
  );
}
