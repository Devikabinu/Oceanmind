"""Fill the local caches of the location report ahead of the clicks: OBIS biodiversity and NOAA ERDDAP context (chlorophyll-a, surface currents).

    python scripts/warm_external_cache.py --points "0,-150;34,-120;-47.6,-165.6"
    python scripts/warm_external_cache.py --grid 20            # every 20 degrees over the Pacific (slow: about half a minute per place)

Nothing is stored that was not retrieved from OBIS or ERDDAP; a place that cannot be fetched is skipped and reported. The report itself never needs this: a click on a place that is not
cached starts the same fetch in the background and shows the stored records meanwhile."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import obis_service, ocean_context  # noqa: E402


def places(args) -> list[tuple[float, float]]:
    if args.points:
        return [tuple(float(x) for x in p.split(",")) for p in args.points.split(";") if p.strip()]       # type: ignore[misc]
    g = args.grid
    lats = [la for la in range(-60, 61, g)]
    lons = [lo if lo <= 180 else lo - 360 for lo in range(100, 291, g)]
    return [(float(la), float(lo)) for la in lats for lo in lons]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--points", help='"lat,lon;lat,lon"')
    ap.add_argument("--grid", type=int, default=0, help="spacing in degrees of a grid over the Pacific")
    args = ap.parse_args()
    if not args.points and not args.grid:
        ap.error("give --points or --grid")
    done = failed = 0
    for lat, lon in places(args):
        try:
            obis_service._save(obis_service._key(lat, lon), obis_service.build(lat, lon))
            ocean_context._save(ocean_context._key(lat, lon), ocean_context.build(lat, lon))
            done += 1
            print(f"cached {lat:+.1f}, {lon:+.1f}")
        except Exception as exc:  # noqa: BLE001 - report and carry on
            failed += 1
            print(f"skipped {lat:+.1f}, {lon:+.1f}: {exc}")
    print(f"{done} places cached, {failed} skipped")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
