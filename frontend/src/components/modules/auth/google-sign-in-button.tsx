/**
 * "Continue with Google" entry point.
 *
 * A full-page navigation (not a fetch) to the backend's Google OAuth start
 * endpoint, which sets a signed state cookie and redirects to Google's consent
 * screen. Rendered as a link styled like the secondary button so it reads as an
 * alternative to the primary email submit, never a duplicate of it.
 *
 * Sign-up requires accepting the Terms first: when `termsAccepted` is false the
 * control is inert and carries no consent, matching the email/password form.
 */
import { resolveApiBaseUrl } from "@/lib/api-base";
import { safeInternalPath } from "@/lib/url/safe-href";

type GoogleSignInButtonProps = {
  /** Resume-intent path forwarded so the user lands where they meant to. */
  next?: string;
  /** Whether the user has accepted the Terms; required to create an account. */
  termsAccepted?: boolean;
  /** Visible label; defaults to the sign-in phrasing. */
  label?: string;
};

/** Build the Google sign-in start URL with optional resume + consent flags. */
function buildStartHref(next?: string, termsAccepted?: boolean): string {
  const params = new URLSearchParams();
  const safeNext = safeInternalPath(next);
  if (safeNext) {
    params.set("next", safeNext);
  }
  if (termsAccepted) {
    params.set("terms", "1");
  }
  const query = params.toString();
  return `${resolveApiBaseUrl()}/v1/auth/google/start${query ? `?${query}` : ""}`;
}

/** The Google "G" mark in its official four colors. */
function GoogleMark() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.88c2.27-2.09 3.57-5.17 3.57-8.87z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3c-1.08.72-2.45 1.16-4.05 1.16-3.11 0-5.75-2.1-6.69-4.93H1.3v3.09A12 12 0 0 0 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.31 14.32a7.2 7.2 0 0 1 0-4.62V6.61H1.3a12 12 0 0 0 0 10.78l4.01-3.07z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.76 0 3.34.61 4.58 1.8l3.43-3.43A11.99 11.99 0 0 0 12 0 12 12 0 0 0 1.3 6.61l4.01 3.09C6.25 6.85 8.89 4.75 12 4.75z"
      />
    </svg>
  );
}

const sharedClasses =
  "inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-xl border px-6 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent";

/**
 * Render the Google sign-in control.
 *
 * @param props - Resume-intent path, consent state, and optional label.
 */
export function GoogleSignInButton({
  next,
  termsAccepted = true,
  label = "Continue with Google",
}: GoogleSignInButtonProps) {
  if (!termsAccepted) {
    return (
      <button
        aria-disabled="true"
        className={`${sharedClasses} cursor-not-allowed border-border-default bg-surface-1 text-foreground-subtle opacity-60`}
        disabled
        type="button"
      >
        <GoogleMark />
        {label}
      </button>
    );
  }

  return (
    <a
      className={`${sharedClasses} border-border-default bg-surface-1 text-foreground hover:bg-surface-2`}
      href={buildStartHref(next, termsAccepted)}
    >
      <GoogleMark />
      {label}
    </a>
  );
}

/** A quiet "or" divider separating Google sign-in from the email form. */
export function AuthDivider() {
  return (
    <div className="flex items-center gap-3" role="separator">
      <span className="h-px flex-1 bg-border-default" />
      <span className="text-xs font-medium uppercase tracking-wide text-foreground-subtle">
        or
      </span>
      <span className="h-px flex-1 bg-border-default" />
    </div>
  );
}
