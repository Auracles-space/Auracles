import React from "react";
import { type AttestorDirectoryEntry } from "@/lib/generated/sdk.gen";

export function AttestorOrgProfile({ org }: { org: AttestorDirectoryEntry }) {
  return (
    <div className="space-y-8">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-8 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div>
            <h1 className="text-3xl font-bold font-heading text-foreground mb-4">
              {org.name}
            </h1>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center space-x-1 px-3 py-1.5 bg-surface-2 border border-border-strong rounded-full text-sm font-semibold">
                <span className="text-foreground-muted">Level</span>
                <span>{org.verification_level}</span>
              </div>
              {org.certification_mark && (
                <div className="flex items-center space-x-1 px-3 py-1.5 bg-surface-2 border border-border-strong rounded-full text-sm font-semibold">
                  <span>{org.certification_mark}</span>
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-foreground">{org.completed_count ?? 0}</p>
              <p className="text-sm font-medium text-foreground-muted uppercase tracking-wider">Attestations</p>
            </div>
            {org.member_count !== undefined && (
              <div className="text-center">
                <p className="text-3xl font-bold text-foreground">{org.member_count}</p>
                <p className="text-sm font-medium text-foreground-muted uppercase tracking-wider">Members</p>
              </div>
            )}
            {org.reputation !== null && (
              <div className="text-center">
                <p className="text-3xl font-bold text-foreground">{org.reputation}</p>
                <p className="text-sm font-medium text-foreground-muted uppercase tracking-wider">Reputation</p>
              </div>
            )}
          </div>
        </div>

        {org.sectors && org.sectors.length > 0 && (
          <div className="mt-8 pt-8 border-t border-border-default">
            <h2 className="text-sm font-semibold text-foreground-muted uppercase tracking-wider mb-4">
              Areas of Expertise
            </h2>
            <div className="flex flex-wrap gap-2">
              {org.sectors.map((sector) => (
                <span key={sector} className="px-3 py-1.5 text-sm bg-surface-2 rounded-md border border-border-default">
                  {sector}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
