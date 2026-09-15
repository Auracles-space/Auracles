/**
 * Organization tax document types: display names and the per-country choices.
 *
 * Mirrors the server rule in `backend/app/modules/organizations/tax_documents.py`:
 * Nigerian orgs declare FIRS documents, every other org the US IRS forms, and
 * "other" is open to all.
 *
 * Maps to: FR-ATT org-attestor tax document gate; Nigeria pilot market.
 */
import type { tax_document_type as TaxDocumentType } from "@/lib/generated/types.gen";

export type { TaxDocumentType };

/** Display names for every tax document type the API accepts. */
export const TAX_DOCUMENT_LABELS: Record<TaxDocumentType, string> = {
  w9: "W-9 (US Persons)",
  w8ben: "W-8BEN (Non-US Persons)",
  firs_tin: "FIRS TIN certificate",
  tcc: "Tax Clearance Certificate (TCC)",
  other: "Other / Exemption",
};

/**
 * Tax document types offered to an org in `country`, default first.
 *
 * @param country - The org's ISO 3166-1 alpha-2 country code.
 * @returns The selectable document types.
 */
export function taxDocumentTypesFor(country: string | undefined): TaxDocumentType[] {
  return country?.toUpperCase() === "NG"
    ? ["firs_tin", "tcc", "other"]
    : ["w9", "w8ben", "other"];
}

/**
 * Display name for a stored tax document type.
 *
 * @param type - The stored `tax_document_type`, possibly null.
 * @returns The label, or an empty string when there is no document.
 */
export function taxDocumentLabel(type: string | null | undefined): string {
  if (!type) return "";
  return TAX_DOCUMENT_LABELS[type as TaxDocumentType] ?? type;
}
