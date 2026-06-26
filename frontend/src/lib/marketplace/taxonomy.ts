/**
 * Marketplace taxonomy options shared by create/edit and Explore surfaces.
 *
 * Values are the canonical API strings stored on Framework rows. Labels are
 * rendered directly where a precise domain name is clearer than title-casing.
 * Source: Auracles Full Spec, taxonomy levels 1-5.
 */

import type {
  FrameworkCategory,
  FrameworkFunction,
  FrameworkIndustry,
  FrameworkSector,
  OrgSize,
} from "@/lib/generated/types.gen";

export type MarketplaceOption<TValue extends string = string> = {
  label: string;
  value: TValue;
};

export const SECTOR_OPTIONS = [
  { label: "Private Equity", value: "private_equity" },
  { label: "Venture Capital", value: "venture_capital" },
  { label: "Infrastructure", value: "infrastructure" },
  { label: "Real Estate", value: "real_estate" },
  { label: "Healthcare", value: "healthcare" },
  { label: "Manufacturing", value: "manufacturing" },
  { label: "Government", value: "government" },
  { label: "Education", value: "education" },
  { label: "Financial Services", value: "financial_services" },
  { label: "Energy", value: "energy" },
  { label: "Telecommunications", value: "telecommunications" },
  { label: "Technology", value: "technology" },
] as const satisfies readonly MarketplaceOption<FrameworkSector>[];

export const INDUSTRY_OPTIONS = [
  { label: "Fund Management", value: "fund_management" },
  { label: "Portfolio Operations", value: "portfolio_operations" },
  { label: "Energy Infrastructure", value: "energy_infrastructure" },
  { label: "Transportation Infrastructure", value: "transportation_infrastructure" },
  { label: "Residential Real Estate", value: "residential_real_estate" },
  { label: "Commercial Real Estate", value: "commercial_real_estate" },
  { label: "Property Management", value: "property_management" },
  { label: "Healthcare Providers", value: "healthcare_providers" },
  { label: "Health Technology", value: "health_technology" },
  { label: "Medical Devices", value: "medical_devices" },
  { label: "Software Engineering", value: "software_engineering" },
  { label: "Data Centers", value: "data_centers" },
  { label: "Renewable Energy", value: "renewable_energy" },
  { label: "Public Sector Agencies", value: "public_sector_agencies" },
] as const satisfies readonly MarketplaceOption<FrameworkIndustry>[];

export const FUNCTION_OPTIONS = [
  { label: "Governance", value: "governance" },
  { label: "Compliance", value: "compliance" },
  { label: "Risk Management", value: "risk_management" },
  { label: "Operations", value: "operations" },
  { label: "Finance", value: "finance" },
  { label: "Legal", value: "legal" },
  { label: "Engineering", value: "engineering" },
  { label: "Human Resources", value: "human_resources" },
  { label: "Sales", value: "sales" },
  { label: "Marketing", value: "marketing" },
  { label: "Product", value: "product" },
  { label: "Data and AI", value: "data_ai" },
  { label: "Information Security", value: "information_security" },
] as const satisfies readonly MarketplaceOption<FrameworkFunction>[];

export const FRAMEWORK_CATEGORY_OPTIONS = [
  { label: "Framework", value: "framework" },
  { label: "Playbook", value: "playbook" },
  { label: "Standard Operating Procedure", value: "sop" },
  { label: "Policy", value: "policy" },
  { label: "Template", value: "template" },
  { label: "Toolkit", value: "toolkit" },
  { label: "Assessment", value: "assessment" },
  { label: "Control Matrix", value: "control_matrix" },
  { label: "Workflow", value: "workflow" },
  { label: "Training Program", value: "training_program" },
] as const satisfies readonly MarketplaceOption<FrameworkCategory>[];

export const ORG_SIZE_OPTIONS = [
  { label: "Startup", value: "startup" },
  { label: "Small Business", value: "small_business" },
  { label: "SME", value: "sme" },
  { label: "Mid Market", value: "mid_market" },
  { label: "Enterprise", value: "enterprise" },
] as const satisfies readonly MarketplaceOption<OrgSize>[];

/**
 * Framework complexity tiers (L1–L5). Values are the stringified integers the
 * backend stores as `complexity` (SMALLINT 1–5) and accepts as an Explore
 * filter query param. Source: Full Spec taxonomy — Complexity L1 Foundational
 * through L5 Enterprise Grade.
 */
export const COMPLEXITY_OPTIONS = [
  { label: "L1 — Foundational", value: "1" },
  { label: "L2 — Developing", value: "2" },
  { label: "L3 — Established", value: "3" },
  { label: "L4 — Advanced", value: "4" },
  { label: "L5 — Enterprise Grade", value: "5" },
] as const satisfies readonly MarketplaceOption[];

/**
 * Framework lifecycle stages. Values are stable snake_case slugs stored on the
 * Framework row (`lifecycle_stage` VARCHAR) and matched exactly by the Explore
 * facet, so create and filter must share this list. Source: Full Spec taxonomy.
 */
export const LIFECYCLE_STAGE_OPTIONS = [
  { label: "Formation", value: "formation" },
  { label: "Early Operations", value: "early_operations" },
  { label: "Growth", value: "growth" },
  { label: "Maturity", value: "maturity" },
  { label: "Optimization", value: "optimization" },
  { label: "Digital Transformation", value: "digital_transformation" },
  { label: "Institutionalization", value: "institutionalization" },
  { label: "Expansion", value: "expansion" },
  { label: "Transformation", value: "transformation" },
  { label: "Exit / Transition", value: "exit_transition" },
  { label: "Legacy & Continuity", value: "legacy_continuity" },
] as const satisfies readonly MarketplaceOption[];

/**
 * Jurisdictions a Framework can be scoped to. Stored as `jurisdiction` VARCHAR
 * and matched exactly by the Explore facet, so create and filter share this
 * canonical list rather than free text (faceted filtering, FR-EXP-004).
 */
export const JURISDICTION_OPTIONS = [
  { label: "Global", value: "global" },
  { label: "United States", value: "united_states" },
  { label: "European Union", value: "european_union" },
  { label: "United Kingdom", value: "united_kingdom" },
  { label: "Nigeria", value: "nigeria" },
  { label: "Canada", value: "canada" },
  { label: "Australia", value: "australia" },
  { label: "Singapore", value: "singapore" },
  { label: "United Arab Emirates", value: "united_arab_emirates" },
  { label: "South Africa", value: "south_africa" },
] as const satisfies readonly MarketplaceOption[];
