import { useState } from "react";
import Alerts from "./Alerts";
import Risk from "./Risk";

const TABS = [
  { id: "alerts", label: "Alerts" },
  { id: "risk", label: "Ecological risk" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function RiskAlerts() {
  const [tab, setTab] = useState<TabId>("alerts");
  return (
    <div>
      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "alerts" ? <Alerts /> : <Risk />}
    </div>
  );
}
