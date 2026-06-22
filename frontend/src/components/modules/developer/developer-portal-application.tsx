"use client";

/**
 * Developer application panel.
 *
 * Renders Partner Developer application status and the access request form for
 * users that are not approved yet.
 */
import type { FormEvent } from "react";
import { useId, useState } from "react";

import type { DeveloperApplicationResponse } from "@/lib/generated/types.gen";
import { allValid, isHttpUrl } from "@/lib/forms/validators";
import { formatLabel } from "@/lib/marketplace/format";

export type ApplicationPayload = Pick<
  DeveloperApplicationResponse,
  "company_name" | "use_case" | "website"
>;

type ApplicationPanelProps = {
  applications: DeveloperApplicationResponse[];
  latestApplication: DeveloperApplicationResponse | null;
  onSubmit: (payload: ApplicationPayload) => Promise<void>;
};

/**
 * Render Developer application status and submission form.
 *
 * @param props - Application history and submit callback.
 */
export function ApplicationPanel({
  applications,
  latestApplication,
  onSubmit,
}: ApplicationPanelProps) {
  const companyId = useId();
  const websiteId = useId();
  const websiteErrorId = useId();
  const useCaseId = useId();
  const [companyName, setCompanyName] = useState("");
  const [website, setWebsite] = useState("");
  const [useCase, setUseCase] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [websiteError, setWebsiteError] = useState<string | null>(null);
  const approved = latestApplication?.status === "approved";

  // Mirror the backend constraints so a valid-looking form never 422s:
  // company_name >= 2 chars, use_case >= 20 chars, website optional but a URL.
  const useCaseRemaining = 20 - useCase.trim().length;
  const canSubmit = allValid(
    companyName.trim().length >= 2,
    useCase.trim().length >= 20,
    website.trim() === "" || isHttpUrl(website),
  ) && !isSubmitting;

  const handleWebsiteChange = (value: string) => {
    setWebsite(value);
    if (value.trim() === "" || isHttpUrl(value)) {
      setWebsiteError(null);
    } else {
      setWebsiteError("Please enter a valid URL starting with http:// or https://");
    }
  };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (website && !isHttpUrl(website)) {
      setWebsiteError("Please enter a valid URL starting with http:// or https://");
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmit({
        company_name: companyName,
        use_case: useCase,
        website: website || null,
      });
      setCompanyName("");
      setWebsite("");
      setUseCase("");
      setWebsiteError(null);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Access
          </p>
          <h2 className="mt-1 font-heading text-xl font-bold">
            Developer application
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Current status: {formatLabel(latestApplication?.status)}
          </p>
        </div>
        {approved ? (
          <span className="w-fit rounded-md border border-success/30 bg-success/10 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-success">
            Approved
          </span>
        ) : null}
      </div>

      {!approved ? (
        <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={companyId}>
            Company
            <input
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              id={companyId}
              onChange={(event) => setCompanyName(event.target.value)}
              required
              disabled={isSubmitting}
              value={companyName}
              placeholder="e.g. Auracles Corp"
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={websiteId}>
            Website
            <input
              className={`min-h-12 rounded-xl border bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 ${
                websiteError ? "border-error focus-visible:ring-error" : "border-border-default"
              }`}
              id={websiteId}
              aria-describedby={websiteError ? websiteErrorId : undefined}
              aria-invalid={websiteError ? true : undefined}
              onChange={(event) => handleWebsiteChange(event.target.value)}
              type="url"
              disabled={isSubmitting}
              value={website}
              placeholder="https://example.com"
            />
          </label>
          {websiteError ? (
            <span className="-mt-1 text-xs text-error font-normal" id={websiteErrorId}>
              {websiteError}
            </span>
          ) : null}
          <label className="grid gap-2 text-sm font-semibold" htmlFor={useCaseId}>
            Use case
            <textarea
              className="min-h-28 rounded-xl border border-border-default bg-surface-2 px-3 py-2 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              id={useCaseId}
              onChange={(event) => setUseCase(event.target.value)}
              required
              disabled={isSubmitting}
              value={useCase}
              placeholder="Describe your integration use case..."
            />
          </label>
          <span className="-mt-1 text-xs font-normal text-foreground-muted">
            {useCaseRemaining > 0
              ? `At least ${useCaseRemaining} more character${useCaseRemaining === 1 ? "" : "s"} needed.`
              : "Looks good."}
          </span>
          <button
            className="min-h-12 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!canSubmit}
            type="submit"
          >
            {isSubmitting ? "Submitting application..." : "Submit application"}
          </button>
        </form>
      ) : null}

      {applications.length > 0 ? (
        <div className="mt-5 grid gap-2">
          {applications.map((application) => (
            <div
              className="rounded-xl border border-border-default bg-surface-2 p-3 text-sm"
              key={application.id}
            >
              <p className="font-semibold">{application.company_name}</p>
              <p className="text-foreground-muted">
                {formatLabel(application.status)} submitted{" "}
                {new Date(application.created_at).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
