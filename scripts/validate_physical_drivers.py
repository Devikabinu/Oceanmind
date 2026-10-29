"""Manual validation of the physical-driver inputs against independent re-derivations (needs the network; not part of the test suite).

    backend/.venv/Scripts/python scripts/validate_physical_drivers.py

A. CCMP wind of the latest week re-derived from the raw ERDDAP rows (scalar mean of the speeds and speed of the mean vector), to compare with the week the application reports.
B. NASA POWER radiation and its 2016-2025 baseline re-derived from the raw JSON, to compare with the anomalies the application reports.
C. A sanity check of the bulk-flux formulas: the ABSOLUTE net heat flux of the normal week computed with them against the NCEP/NCAR Reanalysis 1 1991-2020 climatology of the same days.
   They are different products; their difference is NOT an error bound for the anomaly.
Places are cell centres of the 1 degree SST grid. Each line is printed and nothing is asserted: read the numbers."""
import math
import os
import sys
from datetime import date, timedelta

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(os.path.join(ROOT, "backend"))
from app.services import physical_drivers as pdv  # noqa: E402

UA = {"User-Agent": "OceanMind-validation/1.0"}
PLACES = [("equatorial", 0.375, -149.625, 26.65), ("mid-latitude", -34.625, -96.625, 15.27), ("cold", -47.625, -165.625, 9.68)]      # name, lat, lon, normal SST of the cell on 2026-10-27 (OISST)
LAST_DAY = "2026-10-27"


def part_a():
    print(f"== A. CCMP week re-derived from the raw ERDDAP rows, {LAST_DAY} minus 6 days")
    for name, lat, lon, _ in PLACES:
        lon360 = lon % 360
        start = (date.fromisoformat(LAST_DAY) - timedelta(days=6)).isoformat()
        rng = f"%5B({start}T00:00:00Z):1:({LAST_DAY}T18:00:00Z)%5D%5B({lat - 0.25}):1:({lat + 0.25})%5D%5B({lon360 - 0.25}):1:({lon360 + 0.25})%5D"
        r = requests.get(f"https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ccmp-daily-v2-1-NRT.csv?uwnd{rng},vwnd{rng}", timeout=120, headers=UA)
        rows = [line.split(",") for line in r.text.splitlines()[2:]]
        u, v = np.array([float(x[3]) for x in rows]), np.array([float(x[4]) for x in rows])
        print(f"  {name:13} rows={len(rows)} last={max(x[0] for x in rows)} | mean scalar speed {np.hypot(u, v).mean():.2f} m/s | speed of the mean vector {math.hypot(u.mean(), v.mean()):.2f} m/s")


def part_b():
    print("\n== B. NASA POWER radiation: window 2026-10-13..19 against the same days of 2016-2025, from the raw JSON")
    k = 1000 / 24
    for name, lat, lon, _ in PLACES:
        r = requests.get(pdv.POWER, params={"parameters": pdv.POWER_PARAMS, "community": "RE", "longitude": round(lon, 4), "latitude": round(lat, 4), "start": "20160101", "end": date.today().strftime("%Y%m%d"), "format": "JSON"},
                         timeout=120, headers=UA)
        P = r.json()["properties"]["parameter"]

        def week(year):
            days = [date(year, 10, 19) - timedelta(days=i) for i in range(7)]

            def mean(var):
                vals = [P[var].get(d.strftime("%Y%m%d")) for d in days]
                vals = [x for x in vals if x is not None and x != -999.0]
                return float(np.mean(vals)) if len(vals) >= 6 else None
            return {var: mean(var) for var in ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN", "T2M", "QV2M", "PS")}
        rec = week(2026)
        base = [b for b in (week(y) for y in range(2016, 2026)) if all(x is not None for x in b.values())]
        dsw = 0.94 * (rec["ALLSKY_SFC_SW_DWN"] - np.mean([b["ALLSKY_SFC_SW_DWN"] for b in base])) * k
        dlw = (rec["ALLSKY_SFC_LW_DWN"] - np.mean([b["ALLSKY_SFC_LW_DWN"] for b in base])) * k
        print(f"  {name:13} baseline years={len(base)} | recent SW {rec['ALLSKY_SFC_SW_DWN'] * k:.0f} W/m2, LW {rec['ALLSKY_SFC_LW_DWN'] * k:.0f} W/m2 | net-shortwave anomaly {dsw:+.1f}, downward-longwave anomaly {dlw:+.1f} W/m2")


def part_c():
    print("\n== C. Absolute net flux of the normal week: bulk formulas against the R1 climatology of the same days (a sanity check, not an error bound)")
    for name, lat, lon, sst_normal in PLACES:
        pm = pdv.power_met(lat, lon, date.today())
        ww = pdv.wind_window(lat, lon, date.fromisoformat(pm["dataset_end"]))
        b = pm["baseline"]
        lh, sh = pdv._bulk(sst_normal, ww["baseline"]["speed"]["mean"], b["t2m"]["mean"], b["q"]["mean"], b["ps"]["mean"])
        net = (1 - pdv.ALBEDO) * b["sw"]["mean"] + b["lw"]["mean"] - pdv._lw_up(sst_normal) - lh - sh
        try:
            r1 = pdv.heat_flux_climatology(lat, lon, date.fromisoformat(pm["window"]["start"]), days=7)
        except RuntimeError as exc:
            print(f"  {name:13} R1 climatology unavailable ({exc})")
            continue
        print(f"  {name:13} bulk {net:+.0f} W/m2 (SW {(1 - pdv.ALBEDO) * b['sw']['mean']:.0f}, LWdown {b['lw']['mean']:.0f}, LWup {pdv._lw_up(sst_normal):.0f}, latent {lh:.0f}, sensible {sh:.0f}) | R1 {np.mean(r1['net']):+.0f} W/m2 at {r1['grid_point']}")


if __name__ == "__main__":
    part_a()
    part_b()
    part_c()
