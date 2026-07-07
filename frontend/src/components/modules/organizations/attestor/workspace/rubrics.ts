export type RubricDimension = {
  key: string;
  label: string;
  weight: number;
};

export const RUBRICS: Record<string, RubricDimension[]> = {
  quality: [
    { key: "completeness", label: "Completeness", weight: 0.18 },
    { key: "implementability", label: "Implementability", weight: 0.18 },
    { key: "accuracy", label: "Accuracy", weight: 0.18 },
    { key: "clarity", label: "Clarity", weight: 0.12 },
    { key: "version_currency", label: "Version Currency", weight: 0.10 },
    { key: "appropriate_scope", label: "Appropriate Scope", weight: 0.10 },
    { key: "risk_flags", label: "Risk Flags", weight: 0.08 },
    { key: "recommended_use_cases", label: "Recommended Use Cases", weight: 0.06 },
  ],
  compliance: [
    { key: "regulatory_alignment", label: "Regulatory Alignment", weight: 0.25 },
    { key: "jurisdictional_coverage", label: "Jurisdictional Coverage", weight: 0.20 },
    { key: "control_adequacy", label: "Control Adequacy", weight: 0.20 },
    { key: "evidence_traceability", label: "Evidence Traceability", weight: 0.15 },
    { key: "gap_identification", label: "Gap Identification", weight: 0.12 },
    { key: "update_currency", label: "Update Currency", weight: 0.08 },
  ],
  expert: [
    { key: "technical_soundness", label: "Technical Soundness", weight: 0.25 },
    { key: "methodological_rigor", label: "Methodological Rigor", weight: 0.20 },
    { key: "domain_accuracy", label: "Domain Accuracy", weight: 0.20 },
    { key: "practical_applicability", label: "Practical Applicability", weight: 0.15 },
    { key: "innovation_value", label: "Innovation Value", weight: 0.10 },
    { key: "limitations_disclosure", label: "Limitations Disclosure", weight: 0.10 },
  ],
  provenance: [
    { key: "authorship_verification", label: "Authorship Verification", weight: 0.30 },
    { key: "source_integrity", label: "Source Integrity", weight: 0.25 },
    { key: "originality", label: "Originality", weight: 0.20 },
    { key: "chain_of_custody", label: "Chain of Custody", weight: 0.15 },
    { key: "attribution_completeness", label: "Attribution Completeness", weight: 0.10 },
  ],
};
