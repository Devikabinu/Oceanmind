import { useState } from "react";
import { Link, Outlet } from "react-router-dom";
import NavMenu from "./NavMenu";
import type { NavGroup } from "./NavMenu";
import PlatformStatus from "./PlatformStatus";
import { useAuth } from "../contexts/AuthContext";
import { ActiveSelectionProvider } from "../contexts/ActiveSelection";

const NAV_GROUPS: NavGroup[] = [
  { label: "Dashboard", items: [{ to: "/", label: "Dashboard" }] },
  {
    label: "Explore Ocean",
    items: [
      { to: "/ocean-map", label: "Ocean Map" },
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

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5 text-white">
      <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" aria-hidden>
        <circle cx="16" cy="16" r="15" fill="#0e5a73" stroke="#67d4df" strokeWidth="1.2" />
        <path d="M3 17c3-3 5-3 8 0s5 3 8 0 5-3 8 0" fill="none" stroke="#c6eef2" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M5 22c3-2.5 5-2.5 8 0s5 2.5 8 0 3-1.8 5-1" fill="none" stroke="#67d4df" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M6 12c3-2 5-2 8 0s5 2 8 0 3-1.5 4-1" fill="none" stroke="#67d4df" strokeWidth="1.5" strokeLinecap="round" opacity=".7" />
      </svg>
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">Ocean Environmental Intelligence</span>
        <span className="block text-[11px] uppercase tracking-[0.16em] text-cyan-200/80">Pacific monitoring</span>
      </span>
    </Link>
  );
}

export default function Layout() {
  return (
    <ActiveSelectionProvider>
      <Shell />
    </ActiveSelectionProvider>
  );
}

function Shell() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const userBlock = (
    <div className="flex items-center justify-between gap-2">
      <Link to="/profile" className="min-w-0 truncate text-sm text-sky-100 hover:text-white" title="Profile">
        {user?.full_name} <span className="rounded bg-white/10 px-1.5 py-0.5 text-[11px] font-medium text-cyan-100">{user?.role}</span>
      </Link>
      <button onClick={() => void logout()} className="shrink-0 rounded-md border border-white/30 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/10">
        Log out
      </button>
    </div>
  );

  return (
    <div className="min-h-screen lg:pl-60">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-1.5">Skip to content</a>

      {/* desktop sidebar */}
      <aside className="on-deep fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-gradient-to-b from-deep via-abyss to-deep px-3 py-5 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-6 flex-1 overflow-y-auto pr-1">
          <NavMenu groups={NAV_GROUPS} />
        </div>
        <div className="mt-4 border-t border-white/15 px-2 pt-3">{userBlock}</div>
      </aside>

      {/* top bar: brand and menu on small screens, data context everywhere */}
      <header className="sticky top-0 z-[1100] border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="on-deep flex items-center justify-between gap-3 bg-deep px-4 py-2 lg:hidden">
          <Brand />
          <button
            type="button"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
            className="rounded-md border border-white/30 px-3 py-1.5 text-sm font-medium text-white hover:bg-white/10"
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
        {open && (
          <div id="mobile-nav" className="on-deep max-h-[70vh] space-y-4 overflow-y-auto bg-deep px-4 pb-4 lg:hidden">
            <NavMenu groups={NAV_GROUPS} onNavigate={() => setOpen(false)} />
            <div className="border-t border-white/15 pt-3">{userBlock}</div>
          </div>
        )}
        <div className="px-4 py-2 sm:px-6">
          <PlatformStatus />
        </div>
      </header>

      <main id="main" className="mx-auto max-w-[96rem] px-4 py-6 sm:px-6 sm:py-7">
        <Outlet />
      </main>
    </div>
  );
}
