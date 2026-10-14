import type { BadgeTone } from "../components/Badge";

/** Shared LOW/MEDIUM/HIGH/CRITICAL colouring for risk levels and alert severities. */
export const LEVEL_TONE: Record<"LOW" | "MEDIUM" | "HIGH" | "CRITICAL", BadgeTone> = {
  LOW: "green",
  MEDIUM: "yellow",
  HIGH: "orange",
  CRITICAL: "red",
};
