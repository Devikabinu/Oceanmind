import { Link } from "react-router-dom";
import { useActive } from "../contexts/ActiveSelection";

interface Props {
  /** Selected location (-180..180) to carry along. */
  point?: { lat: number; lon: number } | null;
  eventId?: string | null;
  /** Pages to offer; the current one is simply left out by the caller. */
  to?: ("map" | "risk" | "heatwaves" | "alerts" | "forecast")[];
}

const LABEL = { map: "Ocean map", risk: "Ecological risk", heatwaves: "Marine heatwaves", alerts: "Alerts", forecast: "Forecast" } as const;
const PATH = { map: "/ocean-map", risk: "/ecological-risk", heatwaves: "/heatwaves", alerts: "/alerts", forecast: "/forecast" } as const;

/** Links that carry the active dataset, region, date and selected location to the related feature (conditions → anomaly → heatwave → risk → alert). */
export default function RelatedLinks({ point, eventId, to = ["map", "heatwaves", "risk", "alerts"] }: Props) {
  const act = useActive();
  return (
    <nav aria-label="Related views" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span className="font-semibold uppercase tracking-wide text-slate-600">Follow this through</span>
      {to.map((k) => (
        <Link
          key={k}
          to={`${PATH[k]}${act.toQuery({ lat: point && k !== "alerts" ? point.lat.toFixed(3) : undefined, lon: point && k !== "alerts" ? point.lon.toFixed(3) : undefined, event: k === "heatwaves" ? eventId ?? undefined : undefined })}`}
          className="font-semibold text-tide hover:underline"
        >
          {LABEL[k]} →
        </Link>
      ))}
    </nav>
  );
}
