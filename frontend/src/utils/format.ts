import axios from "axios";

export function formatTimestamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

export function formatCoord(value: number): string {
  return value.toFixed(3);
}

/** Pull a readable message out of an axios/FastAPI error (handles both 422 shapes). */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === "string" ? d : `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`))
        .join("; ");
    }
    if (err.response) return `Request failed (${err.response.status})`;
    return "Could not reach the server";
  }
  return err instanceof Error ? err.message : "Unexpected error";
}
