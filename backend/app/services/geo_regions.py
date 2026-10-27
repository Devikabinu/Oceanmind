"""The ONE definition of Pacific regions and bounding-box handling for every environmental endpoint.

Conventions
  * Region longitudes are EAST longitude 0..360, so a region such as the Central Pacific (170E..120W = 170..240) is a single ordinary box even though it
    crosses +-180. Latitude is -90..90.
  * Region boxes are half-open [min, max) so adjacent regions (north/south of the equator, western/central/eastern Pacific) partition the basin without
    double counting. User-supplied bounding boxes are closed [min, max].
  * Membership is evaluated on `lon mod 360`, so it works for any dataset longitude axis: the Pacific grid (continuous 100.5..289.5), a -180..180 grid, or a
    0..360 grid. A box that crosses +-180 therefore needs no special casing and cannot be torn apart; `column_runs` turns the resulting columns into the
    contiguous index ranges a lazy read needs (two ranges on a -180..180 axis, one on the Pacific axis) and the caller stitches them back together.

Overlaps are intentional and documented where they exist (see `overlap_note`): hierarchy (a child region lies inside its parent) and a few shared seas.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


class UnknownRegion(KeyError):
    pass


@dataclass(frozen=True)
class Box:
    lat_min: float
    lat_max: float
    lon_min: float            # east longitude 0..360
    lon_max: float            # lon_min < lon_max <= 360 (a box never wraps; wrapping requests are split into two boxes)
    closed: bool = False      # True for user bounding boxes (inclusive upper edges), False for regions (half-open)

    def as_dict(self) -> dict:
        return {"lat_min": self.lat_min, "lat_max": self.lat_max, "lon_min": self.lon_min, "lon_max": self.lon_max}


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    description: str
    boxes: tuple[Box, ...] = ()
    parent: str | None = None
    children: tuple[str, ...] = ()
    dataset_wide: bool = False                      # the whole dataset, whatever its extent
    view: tuple[float, float, float, float] | None = None   # (south, west, north, east) suggested map extent, east longitude
    overlap_note: str | None = None

    @property
    def crosses_antimeridian(self) -> bool:
        spans = [(b.lon_min, b.lon_max) for b in self.boxes] or ([(self.view[1], self.view[3])] if self.view else [])
        return any(lo < 180 < hi for lo, hi in spans)


def _b(lat_min, lat_max, lon_min, lon_max) -> Box:
    return Box(lat_min, lat_max, lon_min, lon_max)


_MELANESIA = _b(-23, 0, 140, 183)                  # Fiji is the eastern edge: Tonga and Samoa (about 175W) are Polynesia
_MICRONESIA = _b(0, 22, 130, 180)
_POLYNESIA = _b(-30, 30, 180, 235)                 # the central Pacific islands: not the waters off Mexico and Central America
_EASTER = _b(-32, -20, 235, 255)                    # Easter Island (Rapa Nui) and Salas y Gomez

REGIONS: dict[str, Region] = {r.id: r for r in [
    Region("pacific", "Entire Pacific Ocean", "Every cell of the dataset (the whole processed Pacific domain).", dataset_wide=True, view=(-60, 100, 65, 290),
           children=("western_pacific", "central_pacific", "eastern_pacific", "north_pacific", "south_pacific", "equatorial_pacific", "pacific_islands", "eastern_pacific_americas")),
    Region("western_pacific", "Western Pacific", "East of Asia and Australia: 100E to 170E.", (_b(-90, 90, 100, 170),), "pacific",
           ("east_asia", "southeast_asia", "australia_new_zealand"), view=(-60, 100, 65, 170)),
    Region("central_pacific", "Central Pacific", "170E to 120W (crosses the antimeridian).", (_b(-90, 90, 170, 240),), "pacific", view=(-60, 170, 65, 240)),
    Region("eastern_pacific", "Eastern Pacific", "120W to the Americas (240E and beyond).", (_b(-90, 90, 240, 295),), "pacific", view=(-60, 240, 65, 290)),
    Region("north_pacific", "North Pacific", "North of the equator.", (_b(0, 90, 100, 295),), "pacific", view=(0, 100, 65, 290),
           overlap_note="Partitions the basin with South Pacific (equator belongs to the north)."),
    Region("south_pacific", "South Pacific", "South of the equator.", (_b(-90, 0, 100, 295),), "pacific", view=(-60, 100, 0, 290)),
    Region("equatorial_pacific", "Equatorial Pacific", "Within 10 degrees of the equator, across the whole basin.", (_b(-10, 10, 100, 295),), "pacific", view=(-10, 100, 10, 290),
           overlap_note="Overlaps North and South Pacific only along the equator band (intentional)."),
    Region("east_asia", "East Asia", "Seas of China, Korea, Japan and the Sea of Okhotsk (north of 25N, 100E to 160E).", (_b(25, 65, 100, 160),),
           "western_pacific", view=(25, 100, 65, 160)),
    Region("southeast_asia", "Southeast Asia", "South China Sea, Philippines and Indonesia (12S to 25N, 100E to 141E).", (_b(-12, 25, 100, 141),),
           "western_pacific", view=(-12, 100, 25, 141)),
    Region("australia_new_zealand", "Australia & New Zealand", "Australian east coast, Tasman and Coral seas, New Zealand (50S to 10S, 110E to 180).",
           (_b(-50, -10, 110, 180),), "western_pacific", view=(-50, 110, -10, 180),
           overlap_note="Shares the Coral Sea / south-west Pacific with Melanesia (intentional)."),
    Region("melanesia", "Melanesia", "Papua New Guinea, Solomon Islands, Vanuatu, New Caledonia, Fiji (23S to equator, 140E to 177W).", (_MELANESIA,),
           "pacific_islands", view=(-23, 140, 0, 183)),
    Region("micronesia", "Micronesia", "Palau, Guam, Marshall Islands, Kiribati (equator to 22N, 130E to 180).", (_MICRONESIA,), "pacific_islands",
           view=(0, 130, 22, 180)),
    Region("polynesia", "Polynesia", "Samoa, Tonga, French Polynesia, Hawaii, Easter Island (30S to 30N, 180 to 125W, plus Easter Island).", (_POLYNESIA, _EASTER), "pacific_islands",
           view=(-30, 180, 30, 260)),
    Region("pacific_islands", "Pacific Islands", "Union of Melanesia, Micronesia and Polynesia.", (_MELANESIA, _MICRONESIA, _POLYNESIA, _EASTER), "pacific",
           ("melanesia", "micronesia", "polynesia"), view=(-30, 130, 30, 260),
           overlap_note="Contains the three island regions; Melanesia and Polynesia do not overlap, Micronesia/Polynesia meet at 180."),
    Region("eastern_pacific_americas", "Eastern Pacific / Americas", "The Pacific margin of North and South America: 135W eastwards (225E and beyond).",
           (_b(-90, 90, 225, 295),), "pacific", view=(-60, 225, 65, 290),
           overlap_note="Wider than Eastern Pacific (it adds 135W-120W, the California Current and Gulf of Alaska margin); Eastern Pacific is inside it."),
]}


def get_region(region_id: str) -> Region:
    try:
        return REGIONS[region_id]
    except KeyError:
        raise UnknownRegion(f"unknown region {region_id!r}; valid regions: {', '.join(REGIONS)}") from None


def to_east(lon) -> np.ndarray:
    """Longitude -> east longitude in [0, 360), whatever convention it arrived in."""
    return np.mod(np.asarray(lon, dtype="float64"), 360.0)


def box_mask(lat, lon, boxes) -> np.ndarray:
    """bool (n_lat, n_lon): cells whose centre lies in any box. lon may use any convention."""
    la = np.asarray(lat, dtype="float64")[:, None]
    lo = to_east(lon)[None, :]
    out = np.zeros((la.shape[0], lo.shape[1]), dtype=bool)
    for b in boxes:
        lat_ok = (la >= b.lat_min) & ((la <= b.lat_max) if b.closed else (la < b.lat_max))
        lon_ok = (lo >= b.lon_min) & ((lo <= b.lon_max) if b.closed else (lo < b.lon_max))
        out |= lat_ok & lon_ok
    return out


def region_mask(region: Region, lat, lon) -> np.ndarray:
    if region.dataset_wide:
        return np.ones((len(lat), len(lon)), dtype=bool)
    return box_mask(lat, lon, region.boxes)


def bbox_boxes(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> tuple[Box, ...]:
    """A user bounding box as one or two closed east-longitude boxes.

    min_lon may be larger than max_lon, which means the box crosses a meridian going east: (170, -170) is 170E..190E (crossing +-180), returned as one
    continuous box 170..190, and (350, 10) is split at 0/360. Plain boxes (min_lon <= max_lon) in either -180..180 or 0..360 are accepted; a box spanning
    360 degrees or more selects every longitude."""
    if min_lat > max_lat:
        raise ValueError("min_lat must not be greater than max_lat")
    for v, lo, hi, name in ((min_lat, -90, 90, "min_lat"), (max_lat, -90, 90, "max_lat"), (min_lon, -360, 360, "min_lon"), (max_lon, -360, 360, "max_lon")):
        if not (lo <= v <= hi):
            raise ValueError(f"{name} must be between {lo} and {hi}")
    span = (max_lon - min_lon) % 360.0 if min_lon > max_lon else (max_lon - min_lon)
    if span >= 360.0:
        return (Box(min_lat, max_lat, 0.0, 360.0, True),)
    start = float(np.mod(min_lon, 360.0))
    end = start + span
    if end <= 360.0:
        return (Box(min_lat, max_lat, start, end, True),)
    return (Box(min_lat, max_lat, start, 360.0, True), Box(min_lat, max_lat, 0.0, end - 360.0, True))


def column_runs(cols: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous index runs [start, stop) of True values in a 1-D boolean array: the separate slices needed for a lazy read of a (possibly wrapped) region."""
    idx = np.flatnonzero(cols)
    if idx.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    stops = np.concatenate([idx[breaks] + 1, [idx[-1] + 1]])
    return [(int(a), int(b)) for a, b in zip(starts, stops)]


def lon_ranges_on_axis(lon_min: float, lon_max: float, axis_lo: float, axis_hi: float) -> list[tuple[float, float]]:
    """Intervals, in an axis' own labels, covered by the east-longitude interval [lon_min, lon_max]: one range on a continuous axis, two on a -180..180 axis
    when the interval crosses +-180."""
    out = []
    for k in (-360.0, 0.0, 360.0):
        lo, hi = max(lon_min + k, axis_lo), min(lon_max + k, axis_hi)
        if lo <= hi:
            out.append((lo, hi))
    return sorted(out)


def describe(region: Region) -> dict:
    return {
        "id": region.id, "name": region.name, "description": region.description, "parent": region.parent, "children": list(region.children),
        "dataset_wide": region.dataset_wide, "boxes": [b.as_dict() for b in region.boxes], "crosses_antimeridian": region.crosses_antimeridian,
        "map_extent": None if region.view is None else {"lat_min": region.view[0], "lon_min": region.view[1], "lat_max": region.view[2], "lon_max": region.view[3],
                                                        "lon_convention": "east longitude, continuous (values above 180 are west longitudes)"},
        "overlap_note": region.overlap_note,
    }
