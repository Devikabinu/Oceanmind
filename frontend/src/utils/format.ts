import axios from "axios";

export function formatTimestamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

export function formatCoord(value: number): string {
  return value.toFixed(3);
}

/** Pull a readable message out of an axios/FastAPI error. Never shows stack traces or raw status text. */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string" && err.response && err.response.status < 500) return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === "string" ? d : `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`))
        .join("; ");
    }
    if (!err.response) {
      return err.code === "ECONNABORTED"
        ? "The request took too long and was cancelled. Please try again."
        : "The backend server could not be reached. Check that it is running and that you are online.";
    }
    switch (err.response.status) {
      case 401:
        return "Your session has expired or you are not signed in. Please log in again.";
      case 403:
        return "Your account role does not allow this action.";
      case 404:
        return typeof detail === "string" ? detail : "The requested item was not found.";
      case 502:
      case 503:
        return typeof detail === "string" ? detail : "A required data source is temporarily unavailable.";
      default:
        return "The server hit an unexpected problem. Please try again in a moment.";
    }
  }
  return err instanceof Error ? err.message : "Unexpected error";
}

/** True when the failure means "the data source / backend is not available" rather than "nothing matched". */
export function isUnavailable(message: string | null): boolean {
  return !!message;
}

/** One sentence for an empty list: distinguishes "nothing is stored yet" from "your filters matched nothing". */
export function emptyListMessage(noun: string, isFiltered: boolean, howToLoad: string): string {
  return isFiltered
    ? `No ${noun} match the filters you applied. Try widening or clearing them.`
    : `No ${noun} are stored yet. ${howToLoad}`;
}
