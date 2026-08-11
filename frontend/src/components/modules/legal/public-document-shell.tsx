/**
 * Shared shell for public legal and policy documents.
 *
 * Keeps long-form policy pages readable while preserving the marketing header,
 * footer, and Auracles bento surface language. The side panel provides stable
 * document context without changing the legal copy itself.
 */
import type { ReactNode } from "react";
import Link from "next/link";

import { FooterCta } from "@/components/modules/landing/footer-cta";
import { MarketingNav } from "@/components/modules/landing/marketing-nav";

type PublicDocumentShellProps = {
  acknowledgement?: string;
  children: ReactNode;
  description: string;
  title: string;
  updated: string;
  version: string;
};

const relatedDocuments = [
  { href: "/privacy", label: "Privacy" },
  { href: "/security", label: "Security" },
  { href: "/terms", label: "Terms" },
];

/**
 * Render a public document with document metadata, related links, and body copy.
 *
 * @param props - Document metadata and long-form body content.
 */
export function PublicDocumentShell({
  acknowledgement,
  children,
  description,
  title,
  updated,
  version,
}: PublicDocumentShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <MarketingNav />
      <main className="flex-1 px-5 py-10 md:px-10 md:py-16 lg:py-20">
        <div className="mx-auto grid w-full max-w-[1180px] gap-6 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
          <aside className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-6 lg:sticky lg:top-24">
            <h1 className="font-heading text-3xl font-bold tracking-tight text-foreground md:text-4xl">
              {title}
            </h1>
            <p className="mt-4 text-sm leading-6 text-foreground-muted">
              {description}
            </p>

            <dl className="mt-6 grid gap-3 border-t border-border-default pt-5 text-sm">
              <div>
                <dt className="font-semibold text-foreground">Version</dt>
                <dd className="mt-1 text-foreground-muted">{version}</dd>
              </div>
              <div>
                <dt className="font-semibold text-foreground">Updated</dt>
                <dd className="mt-1 text-foreground-muted">{updated}</dd>
              </div>
            </dl>

            <nav
              aria-label="Related documents"
              className="mt-6 border-t border-border-default pt-5"
            >
              <p className="font-heading text-sm font-semibold text-foreground">
                Related documents
              </p>
              <ul className="mt-3 grid gap-2">
                {relatedDocuments.map((document) => (
                  <li key={document.href}>
                    <Link
                      className="flex min-h-11 items-center rounded-xl px-3 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
                      href={document.href}
                    >
                      {document.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </aside>

          <article className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8 lg:p-10">
            <div className="mx-auto max-w-[74ch] space-y-8 text-base leading-7 text-foreground-muted">
              {children}
            </div>

            {acknowledgement ? (
              <div className="mx-auto mt-10 max-w-[74ch] border-t border-border-default pt-6 text-sm leading-6 text-foreground-subtle">
                <p>{acknowledgement}</p>
              </div>
            ) : null}
          </article>
        </div>
      </main>
      <FooterCta />
    </div>
  );
}
