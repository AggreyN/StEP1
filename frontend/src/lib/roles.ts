// Mirror of backend/app/sources/roles.py ROLE_LABELS (the 14 real roles;
// `other` is deliberately excluded — nobody picks "Other" as a field of
// interest). Keep in sync with the backend if the taxonomy changes.
import type { RoleKey } from "./types";

export const ROLE_LABELS: Record<RoleKey, string> = {
  software: "Software Engineering",
  ai_ml_data: "AI / ML / Data Science",
  data_analytics: "Data & Business Analytics",
  hardware: "Hardware & Embedded",
  quant: "Quantitative Finance",
  product_management: "Product Management",
  program_management: "Technical Program Management",
  solutions_architecture: "Solutions & Sales Engineering",
  security: "Security",
  infra_devops: "Cloud, Infra & DevOps",
  design_ux: "Design & UX",
  it_support: "IT & Systems",
  tech_consulting: "Technology Consulting",
  research: "Research",
};

export const ROLE_KEYS = Object.keys(ROLE_LABELS) as RoleKey[];

export function roleLabel(key: string): string {
  return (ROLE_LABELS as Record<string, string>)[key] ?? key;
}
