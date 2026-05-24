// v11c retention-scoring — colored chip for cohort labels. Reused
// on the customer list filter toolbar and the customer detail header.
//
// Colors are tuned to read as "increasing concern": blue/green for
// new/active, amber/orange for slipping, red for lost. Tailwind utility
// classes inline so we don't need new design tokens.

export type Cohort = "new" | "active" | "at_risk" | "dormant" | "lost";

const COHORT_LABELS: Record<Cohort, string> = {
  new: "New",
  active: "Active",
  at_risk: "At risk",
  dormant: "Dormant",
  lost: "Lost",
};

const COHORT_CLASSES: Record<Cohort, string> = {
  new: "pd-chip pd-chip--cohort-new",
  active: "pd-chip pd-chip--cohort-active",
  at_risk: "pd-chip pd-chip--cohort-at-risk",
  dormant: "pd-chip pd-chip--cohort-dormant",
  lost: "pd-chip pd-chip--cohort-lost",
};

// Inline backgrounds — these survive even without the matching CSS
// utility class so unit tests can assert the visual signal directly.
const COHORT_STYLE: Record<Cohort, React.CSSProperties> = {
  new: { background: "#dbeafe", color: "#1e40af" }, // blue
  active: { background: "#dcfce7", color: "#15803d" }, // green
  at_risk: { background: "#fef3c7", color: "#92400e" }, // amber
  dormant: { background: "#ffedd5", color: "#9a3412" }, // orange
  lost: { background: "#fee2e2", color: "#991b1b" }, // red
};

export interface CohortChipProps {
  cohort: Cohort | string | null | undefined;
  count?: number | null;
}

export function CohortChip({ cohort, count }: CohortChipProps) {
  if (!cohort || !(cohort in COHORT_LABELS)) {
    return (
      <span className="pd-chip pd-chip--ghost" data-testid="cohort-chip">
        —
      </span>
    );
  }
  const c = cohort as Cohort;
  return (
    <span
      className={COHORT_CLASSES[c]}
      style={COHORT_STYLE[c]}
      data-testid="cohort-chip"
      data-cohort={c}
    >
      {COHORT_LABELS[c]}
      {typeof count === "number" ? ` (${count})` : ""}
    </span>
  );
}

export const COHORT_ORDER: Cohort[] = ["new", "active", "at_risk", "dormant", "lost"];
export { COHORT_LABELS };
