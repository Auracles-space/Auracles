/**
 * Framework preview artifact block.
 *
 * The preview URL is short-lived and read-only; licensed downloads still go
 * through the Operator library/download gate.
 */
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";
import { formatFileSize } from "@/lib/marketplace/format";
import { safeHref } from "@/lib/url/safe-href";

type PreviewArtifactBlockProps = {
  framework: ExploreFrameworkDetail;
};

/**
 * Render the public preview artifact and artifact manifest.
 *
 * @param props - Public Framework detail including preview URL.
 */
export function PreviewArtifactBlock({ framework }: PreviewArtifactBlockProps) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="font-heading text-lg font-bold text-foreground">
        Preview
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Public preview is separate from licensed artifact download access.
      </p>
      {safeHref(framework.preview_url) ? (
        <a
          className="mt-4 inline-flex min-h-12 items-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
          href={safeHref(framework.preview_url)}
          rel="noreferrer noopener"
          target="_blank"
        >
          Open preview artifact
        </a>
      ) : (
        <p className="mt-4 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
          Preview artifact is not available.
        </p>
      )}
      <div className="mt-5 divide-y divide-border-default">
        {framework.artifacts.map((artifact) => (
          <div className="py-3 text-sm" key={artifact.id}>
            <p className="font-semibold text-foreground">{artifact.name}</p>
            <p className="text-foreground-muted">
              {artifact.mime_type} · {formatFileSize(artifact.file_size)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
