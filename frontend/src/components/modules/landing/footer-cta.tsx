"use client";

/**
 * Footer CTA strip + site footer.
 *
 * Bottom gradient panel mirrors the hero blob and closes the page on the
 * marketplace's primary call: register. Below, a slim site footer with
 * legal + contact links.
 */
import Link from "next/link";
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { joinWaitlistV1WaitlistPost } from "@/lib/generated/sdk.gen";

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";



/**
 * Render the closing gradient CTA and the site footer.
 */
export function FooterCta() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [alreadyJoined, setAlreadyJoined] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    configureBrowserClient();
    const result = await joinWaitlistV1WaitlistPost({
      body: { email, source: "footer" },
    });
    setIsSubmitting(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAlreadyJoined(result.data.already_joined);
    setSubmitted(true);
  };

  const footerGroups = [
    {
      title: "Platform",
      links: [
        { href: "#roles", label: "For Contributors" },
        { href: "#how-it-works", label: "How it Works" },
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
    {
      title: "Social",
      links: [
        { href: "https://linkedin.com", label: "LinkedIn" },
        { href: "https://x.com", label: "X" },
        { href: "https://github.com", label: "Github" },
      ],
    },
  ];

  return (
    <>
      <section className="w-full" id="waitlist-form">
        <div className="bg-background px-5 py-20 text-center md:py-28">
          <div className="mx-auto max-w-[1280px]">
            <h2 className="font-heading text-4xl font-bold tracking-tight text-foreground md:text-5xl lg:text-6xl">
              Be known for what you&apos;ve built
            </h2>
            <p className="mt-4 text-base text-foreground-muted md:text-lg">
              {isWaitlistMode
                ? "Join the waitlist and help build the Framework Economy."
                : "Register today and help build the Framework Economy."}
            </p>

            {isWaitlistMode ? (
              submitted ? (
                <div className="mt-10 flex flex-col items-center justify-center gap-3 rounded-2xl border border-success/30 bg-success/5 p-6 max-w-md mx-auto animate-fade-in">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-success/10 text-success text-lg font-bold">
                    ✓
                  </span>
                  <p className="text-sm font-semibold text-foreground">
                    {alreadyJoined
                      ? "You're already on the waitlist!"
                      : "You've been added to the waitlist!"}
                  </p>
                  <p className="text-xs text-foreground-muted text-center">
                    {alreadyJoined ? (
                      <>
                        <strong className="text-foreground">{email}</strong> is
                        already reserved. We&apos;ll reach out as soon as slots
                        open up.
                      </>
                    ) : (
                      <>
                        We&apos;ve reserved a spot for{" "}
                        <strong className="text-foreground">{email}</strong>.
                        We&apos;ll reach out as soon as slots open up.
                      </>
                    )}
                  </p>
                </div>
              ) : (
                <form
                  onSubmit={handleSubmit}
                  className="mx-auto mt-10 flex max-w-md flex-col gap-3 sm:flex-row items-stretch"
                >
                  <div className="flex-1">
                    <input
                      type="email"
                      required
                      disabled={isSubmitting}
                      placeholder="Email address"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full h-12 rounded-control border border-border-strong bg-surface-1 px-4 text-sm text-foreground placeholder:text-foreground-subtle outline-none focus:border-accent focus:ring-1 focus:ring-accent disabled:opacity-60"
                    />
                    {error ? (
                      <p className="mt-2 text-left text-xs text-error">{error}</p>
                    ) : null}
                  </div>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex h-12 items-center justify-center rounded-control bg-accent px-6 text-sm font-semibold text-white shadow transition hover:opacity-90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isSubmitting ? "Joining..." : "Join waitlist"}
                  </button>
                </form>
              )
            ) : (
              <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Link
                  className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control bg-accent px-6 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
                  href="/register"
                >
                  Create an account
                </Link>
                <Link
                  className="inline-flex h-12 min-w-[180px] items-center justify-center rounded-control border border-border-strong bg-surface-1 px-6 text-sm font-medium text-foreground transition hover:bg-surface-2"
                  href="/explore"
                >
                  Browse the catalog
                </Link>
              </div>
            )}
          </div>
        </div>
      </section>


      <footer className="bg-background border-t border-border-default">
        <div className="mx-auto grid w-full max-w-[1280px] gap-10 px-5 py-16 md:grid-cols-[1.4fr_1fr_1fr_1fr] md:px-10">
          <div>
            <div className="font-heading text-xl font-bold text-foreground">
              Auracles
            </div>
            <p className="mt-4 max-w-xs text-sm leading-6 text-foreground-muted">
              The marketplace for professional frameworks and reusable knowledge assets.
            </p>
          </div>
          {footerGroups.map((group) => (
            <div key={group.title}>
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-foreground-subtle">
                {group.title}
              </p>
              <ul className="mt-6 space-y-4 text-sm font-medium text-foreground-muted">
                {group.links.map((link) => (
                  <li key={link.label}>
                    {link.href.startsWith("#") ? (
                      <a
                        className="transition hover:text-accent"
                        href={link.href}
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        className="transition hover:text-accent"
                        href={link.href}
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="border-t border-border-default bg-surface-2">
          <div className="mx-auto flex w-full max-w-[1280px] flex-col justify-between gap-4 px-5 py-8 text-xs font-medium text-foreground-subtle md:flex-row md:px-10">
            <p>© {new Date().getFullYear()} Auracles. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </>
  );
}


