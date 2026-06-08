/**
 * Operator library route.
 */
import { OperatorLibrary } from "@/components/modules/library/operator-library";

/**
 * Render the Operator's licensed Framework library.
 */
export default function LibraryPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Operator library
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Licensed frameworks
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Download the licensed version snapshots available to your account.
          </p>
        </header>
        <OperatorLibrary />
      </div>
    </main>
  );
}
