import Badge from "./Badge";
import type { BadgeTone } from "./Badge";

const TONE: Record<string, BadgeTone> = { CR: "red", EN: "orange", VU: "yellow", NT: "blue", LC: "green", DD: "slate", NE: "slate", EW: "red", EX: "slate" };
const FALLBACK: Record<string, string> = {
  CR: "Critically Endangered",
  EN: "Endangered",
  VU: "Vulnerable",
  NT: "Near Threatened",
  LC: "Least Concern",
  DD: "Data Deficient",
  NE: "Not Evaluated",
  EW: "Extinct in the Wild",
  EX: "Extinct",
};

/** Conservation status exactly as a source reports it. No category = "Status not confirmed" (never silently Least Concern). */
export default function ConservationBadge({ category, label, source }: { category: string | null; label: string | null; source?: string | null }) {
  if (!category) {
    return (
      <span title="No source used by this project reports an IUCN category for this species, so none is shown. It is NOT the same as Least Concern.">
        <Badge tone="slate">Status not confirmed</Badge>
      </span>
    );
  }
  return (
    <span title={source ?? "IUCN Red List category as reported by the data source"}>
      <Badge tone={TONE[category] ?? "slate"}>{`${label ?? FALLBACK[category] ?? category} (${category})`}</Badge>
    </span>
  );
}
