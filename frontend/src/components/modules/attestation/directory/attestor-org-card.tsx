import React from "react";
import Link from "next/link";
import { type AttestorDirectoryEntry } from "@/lib/generated/sdk.gen";

export function AttestorOrgCard({ org }: { org: AttestorDirectoryEntry }) {
  return (
    <Link
      href={`/attestors/${org.org_id}`}
      className="block group rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm transition-all hover:border-accent/40 hover:bg-surface-2 hover:shadow-md"
    >
      <div className="flex items-start justify-between mb-4">
        <h2 className="text-xl font-bold font-heading text-foreground group-hover:text-accent transition-colors">
          {org.name}
        </h2>
        <div className="flex items-center space-x-1 px-2 py-1 bg-surface-2 border border-border-strong rounded-full text-xs font-semibold">
          <span className="text-foreground-muted">Level</span>
          <span>{org.verification_level}</span>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-2">
            Expertise
          </p>
          <div className="flex flex-wrap gap-2">
            {org.sectors.slice(0, 3).map((sector) => (
              <span key={sector} className="px-2 py-1 text-xs bg-surface-2 rounded-md border border-border-default">
                {sector}
              </span>
            ))}
            {org.sectors.length > 3 && (
              <span className="px-2 py-1 text-xs bg-surface-2 rounded-md border border-border-default">
                +{org.sectors.length - 3} more
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-border-default">
          <div className="text-sm">
            <span className="font-semibold text-foreground">{org.completed_count ?? 0}</span>
            <span className="text-foreground-muted ml-1">Attestations</span>
          </div>
          {org.member_count !== undefined && (
            <div className="text-sm">
              <span className="font-semibold text-foreground">{org.member_count}</span>
              <span className="text-foreground-muted ml-1">Members</span>
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
