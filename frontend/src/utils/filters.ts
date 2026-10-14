import type { FilterField } from "../components/FilterPanel";

export const DATE_RANGE_FIELDS: FilterField[] = [
  { name: "start_date", label: "From", type: "date" },
  { name: "end_date", label: "To", type: "date" },
];

export const BBOX_FIELDS: FilterField[] = [
  { name: "min_latitude", label: "Min lat", type: "number", min: -90, max: 90 },
  { name: "max_latitude", label: "Max lat", type: "number", min: -90, max: 90 },
  { name: "min_longitude", label: "Min lon", type: "number", min: -180, max: 180 },
  { name: "max_longitude", label: "Max lon", type: "number", min: -180, max: 180 },
];

export const GEO_TIME_FIELDS: FilterField[] = [...DATE_RANGE_FIELDS, ...BBOX_FIELDS];

/** Drop empty values; make the date range inclusive of the whole end day. */
export function toQueryParams(values: Record<string, string>): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === "") continue;
    if (key === "start_date") params[key] = `${value}T00:00:00Z`;
    else if (key === "end_date") params[key] = `${value}T23:59:59Z`;
    else params[key] = value;
  }
  return params;
}
