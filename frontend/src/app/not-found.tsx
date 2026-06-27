import Link from "next/link";
import { MarketingNav } from "@/components/modules/landing/marketing-nav";

/**
 * Global 404 Not Found page.
 *
 * Inherits from the root layout, so we include the MarketingNav to ensure
 * users have a way out. Uses the brand's aesthetic (warm orange accent,
 * rounded controls) to provide a soft landing.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <MarketingNav />
      
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-24 sm:py-32 lg:px-8 text-center">
        <p className="text-base font-semibold leading-8 text-accent">404</p>
        <h1 className="mt-4 font-heading text-3xl font-bold tracking-tight text-foreground sm:text-5xl">
          Page not found
        </h1>
        <p className="mt-6 text-base leading-7 text-foreground-muted max-w-md mx-auto">
          Sorry, we couldn&apos;t find the page you&apos;re looking for. It might have been moved, deleted, or never existed in the first place.
        </p>
        
        <div className="mt-10 flex items-center justify-center gap-x-4">
          <Link
            href="/"
            className="inline-flex min-h-12 items-center justify-center rounded-xl border border-transparent bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
          >
            Go back home
          </Link>
          <Link
            href="/explore"
            className="text-sm font-medium leading-6 text-foreground hover:text-accent transition-colors"
          >
            Browse frameworks <span aria-hidden="true">&rarr;</span>
          </Link>
        </div>
      </main>
    </div>
  );
}
