import { Link, Outlet } from "react-router-dom";
import NavMenu from "./NavMenu";
import type { NavGroup } from "./NavMenu";
import { useAuth } from "../contexts/AuthContext";

const NAV_GROUPS: NavGroup[] = [
  { label: "Dashboard", items: [{ to: "/", label: "Dashboard" }] },
  {
    label: "Explore Ocean",
    items: [
      { to: "/map", label: "Ocean Map" },
      { to: "/forecast", label: "Forecast" },
      { to: "/anomaly", label: "Anomalies" },
    ],
  },
  {
    label: "Marine Biodiversity",
    items: [
      { to: "/species", label: "Species" },
      { to: "/ecological-risk?tab=species", label: "Species Risk" },
    ],
  },
  {
    label: "Environmental Risk",
    items: [
      { to: "/heatwaves", label: "Marine Heatwaves" },
      { to: "/ecological-risk", label: "Ecological Risk" },
      { to: "/alerts", label: "Alerts" },
    ],
  },
  { label: "Ocean Data", items: [{ to: "/ocean-data", label: "Ocean Data" }] },
  { label: "Model Performance", items: [{ to: "/performance", label: "Model Performance" }] },
];

export default function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-1.5">Skip to content</a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-3">
          <div className="flex min-w-0 items-center gap-8">
            <span className="shrink-0 text-sm font-semibold tracking-tight text-slate-900">
              Ocean Environmental Intelligence
            </span>
            <NavMenu groups={NAV_GROUPS} />
          </div>
          <div className="flex items-center gap-3">
            <Link to="/profile" className="text-sm text-slate-500 hover:text-slate-900" title="Profile">
              {user?.full_name}{" "}
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">
                {user?.role}
              </span>
            </Link>
            <button
              onClick={() => void logout()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
        <Outlet />
      </main>
    </div>
  );
}
