export const ROLE_LABELS = {
  homeowner: "Homeowner",
  architect: "Architect / designer",
  kohler: "Kohler team",
  admin: "Admin",
};

export const REPORT_DESCRIPTIONS = {
  homeowner: "Cost vs budget, water saved, products and the plan.",
  architect: "Adds dimensions, clearances, placement schedule and compliance checks.",
  kohler: "Adds SKUs, bundle-selection maths, AI pipeline trace and product features.",
  admin: "Full Kohler-team detail.",
};

export const SELF_SERVICE_ROLES = ["homeowner", "architect"];

export const REPORT_TYPES = [
  { id: "homeowner", label: "Homeowner", blurb: "Cost, water saved, products, plan" },
  { id: "architect", label: "Architect / designer", blurb: "+ dimensions, clearances, placement schedule" },
  { id: "kohler", label: "Kohler team", blurb: "+ SKUs, selection maths, AI trace" },
];

/** The report a user gets by default, and whether they may pick the Kohler one. */
export function canUseKohlerReport(role) {
  return role === "kohler" || role === "admin";
}

export function defaultReportType(role) {
  if (canUseKohlerReport(role)) return "kohler";
  return role === "architect" ? "architect" : "homeowner";
}
