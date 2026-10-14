import { Outlet } from "react-router-dom";
import NavMenu from "./NavMenu";
import type { NavGroup } from "./NavMenu";
import { useAuth } from "../contexts/AuthContext";

const NAV_GROUPS: NavGroup[] = [
  { label: "Overview", items: [{ to: "/", label: "Dashboard" }] },
  {
    label: "Data",
    items: [
      { to: "/data-sources", label: "Data Sources" },
      { to: "/datasets", label: "Datasets" },
      { to: "/ingestion", label: "Ingestion" },
      { to: "/data-quality", label: "Data Quality" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/forecast", label: "Forecast" },
      { to: "/anomaly", label: "Anomalies" },
      { to: "/risk", label: "Risk" },
      { to: "/alerts", label: "Alerts" },
    ],
  },
  { label: "Account", items: [{ to: "/profile", label: "Profile" }] },
];

export default function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-3">
          <div className="flex min-w-0 items-center gap-8">
            <span className="shrink-0 text-sm font-semibold tracking-tight text-slate-900">
              Ocean Environmental Intelligence
            </span>
            <NavMenu groups={NAV_GROUPS} />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500">
              {user?.full_name}{" "}
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">
                {user?.role}
              </span>
            </span>
            <button
              onClick={() => void logout()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
