import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

export interface NavItem {
  to: string;
  label: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

const PILL = "shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors";
const PILL_ACTIVE = "bg-slate-900 text-white";
const PILL_IDLE = "text-slate-600 hover:bg-slate-100 hover:text-slate-900";

function GroupMenu({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  const isActive = group.items.some((item) => pathname === item.to);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`${PILL} flex items-center gap-1 ${isActive ? PILL_ACTIVE : PILL_IDLE}`}
      >
        {group.label}
        <span aria-hidden className={`text-[10px] transition-transform ${open ? "rotate-180" : ""}`}>
          &#9660;
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 z-20 mt-1 min-w-44 rounded-md border border-slate-200 bg-white py-1 shadow-md"
        >
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              role="menuitem"
              onClick={() => setOpen(false)}
              className={({ isActive: linkActive }) =>
                `block px-4 py-2 text-sm ${
                  linkActive
                    ? "bg-slate-100 font-medium text-slate-900"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

/** Single-link groups render as a plain link; multi-link groups as a dropdown. */
export default function NavMenu({ groups }: { groups: NavGroup[] }) {
  return (
    <nav className="flex items-center gap-1">
      {groups.map((group) =>
        group.items.length === 1 ? (
          <NavLink
            key={group.label}
            to={group.items[0].to}
            end={group.items[0].to === "/"}
            className={({ isActive }) => `${PILL} ${isActive ? PILL_ACTIVE : PILL_IDLE}`}
          >
            {group.label}
          </NavLink>
        ) : (
          <GroupMenu key={group.label} group={group} />
        ),
      )}
    </nav>
  );
}
