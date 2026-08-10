"use client";

/**
 * Footer CTA strip + site footer.
 *
 * Bottom gradient panel mirrors the hero blob and closes the page on the
 * marketplace's primary call: register. Below, a slim site footer with
 * legal + contact links.
 */
import { CheckIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useState } from "react";

import { BrandLogo } from "@/components/ui/brand-logo";

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
        { href: "#become", label: "Become an Auracle" },
        { href: "#pricing", label: "Licensing" },
        { href: "#faq", label: "FAQ" },
      ],
    },
    {
      title: "Company",
      links: [
        { href: "mailto:admin@auracles.space", label: "Contact" },
        { href: "/terms", label: "Terms" },
        { href: "/privacy", label: "Privacy" },
        { href: "/security", label: "Security" },
      ],
    },
    {
      title: "Social",
      links: [
        { href: "https://www.linkedin.com/company/auraclespace", label: "LinkedIn" },
        { href: "https://x.com/Auraclespace", label: "X" },
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
                <div
                  className="mt-10 flex flex-col items-center justify-center gap-3 rounded-2xl border border-success/30 bg-success/5 p-6 max-w-md mx-auto animate-fade-in"
                  role="status"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-success/10 text-success">
                    <CheckIcon aria-hidden="true" className="h-6 w-6" />
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
                    <label className="sr-only" htmlFor="waitlist-email">
                      Email address
                    </label>
                    <input
                      type="email"
                      id="waitlist-email"
                      required
                      autoComplete="email"
                      spellCheck={false}
                      disabled={isSubmitting}
                      placeholder="Email address"
                      value={email}
                      aria-invalid={error ? true : undefined}
                      aria-describedby={error ? "waitlist-email-error" : undefined}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (error) setError(null);
                      }}
                      className={`w-full h-12 rounded-control border bg-surface-1 px-4 text-sm text-foreground placeholder:text-foreground-subtle outline-none transition-colors disabled:opacity-60 ${
                        error
                          ? "border-error focus:border-error focus:ring-1 focus:ring-error"
                          : "border-border-strong focus:border-accent focus:ring-1 focus:ring-accent"
                      }`}
                    />
                    {error ? (
                      <p
                        className="mt-2 text-left text-xs font-semibold text-error"
                        id="waitlist-email-error"
                        role="alert"
                      >
                        {error}
                      </p>
                    ) : null}
                  </div>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex h-12 items-center justify-center rounded-control bg-accent px-6 text-sm font-semibold text-white shadow transition hover:opacity-90 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isSubmitting ? (
                      <>
                        <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                        Joining...
                      </>
                    ) : (
                      "Join waitlist"
                    )}
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
            <BrandLogo className="h-8 w-32" />
            <p className="mt-4 max-w-xs text-sm leading-6 text-foreground-muted">
              The marketplace for professional frameworks and reusable knowledge assets.
            </p>
          </div>
          {footerGroups.map((group) => (
            <div key={group.title}>
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-foreground-subtle">
                {group.title}
              </p>
              <ul className="mt-4 space-y-1 text-sm font-medium text-foreground-muted">
                {group.links.map((link) => {
                  const isExternal = link.href.startsWith("http");
                  const className =
                    "inline-flex min-h-11 items-center rounded-control transition hover:text-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-background";

                  return (
                    <li key={link.label}>
                      {link.href.startsWith("#") || isExternal ? (
                        <a
                          className={className}
                          href={link.href}
                          {...(isExternal && {
                            rel: "noopener noreferrer",
                            target: "_blank",
                          })}
                        >
                          {link.label}
                        </a>
                      ) : (
                        <Link className={className} href={link.href}>
                          {link.label}
                        </Link>
                      )}
                    </li>
                  );
                })}
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


