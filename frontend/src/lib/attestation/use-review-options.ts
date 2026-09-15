"use client";

/**
 * Data hooks for choosing an attestation review type.
 *
 * `useReviewTypes` reads every review type with its summary and live fee;
 * `useAttestedReviewTypes` reads which review types a framework already holds
 * for its current version. Both fail quietly to empty results: they add
 * guidance to the request form, and the server still enforces the rules.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useEffect, useState } from "react";

import { getExploreFrameworkDetail, listAttestationReviewTypes } from "@/lib/generated/sdk.gen";
import type { ReviewTypeOption } from "@/lib/generated/types.gen";
import { attestedOnCurrentVersion } from "@/lib/attestation/in-flight";

/**
 * Load the framework review types with their summaries and fees.
 *
 * @returns The review types, or an empty list until loaded or on failure.
 */
export function useReviewTypes(): ReviewTypeOption[] {
  const [reviewTypes, setReviewTypes] = useState<ReviewTypeOption[]>([]);
  useEffect(() => {
    let active = true;
    async function load() {
      const result = await listAttestationReviewTypes();
      if (active && result.response?.ok && result.data) {
        setReviewTypes(result.data.review_types);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);
  return reviewTypes;
}

/**
 * Load the review types a framework holds for its current version.
 *
 * @param frameworkId - The framework, or an empty string when none is chosen.
 * @returns Outcome keyed by review type.
 */
export function useAttestedReviewTypes(frameworkId: string): Record<string, string> {
  const [attested, setAttested] = useState<Record<string, string>>({});
  useEffect(() => {
    setAttested({});
    if (!frameworkId) return;
    let active = true;
    async function load() {
      const result = await getExploreFrameworkDetail({
        path: { framework_id: frameworkId },
      });
      if (active && result.response?.ok && result.data) {
        setAttested(attestedOnCurrentVersion(result.data.attestation_badges ?? []));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [frameworkId]);
  return attested;
}
