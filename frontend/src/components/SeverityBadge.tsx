import type { Level } from "../api/monitor";

// Colour is never the only signal: every level also has a distinct symbol and its name in text.
const STYLE: Record<Level, { cls: string; icon: string }> = {
  LOW: { cls: "bg-green-100 text-green-900 ring-green-300", icon: "●" },
  MEDIUM: { cls: "bg-yellow-100 text-yellow-900 ring-yellow-400", icon: "◆" },
  HIGH: { cls: "bg-orange-100 text-orange-900 ring-orange-400", icon: "▲" },
  CRITICAL: { cls: "bg-red-100 text-red-900 ring-red-400", icon: "⬣" },
};

export default function SeverityBadge({ level }: { level: Level }) {
  const s = STYLE[level];
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${s.cls}`}>
      <span aria-hidden>{s.icon}</span>
      {level === "MEDIUM" ? "MODERATE" : level}
    </span>
  );
}
